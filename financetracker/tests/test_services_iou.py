from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from financetracker.models import Category, IOU, IOURepayment, Transaction
from financetracker.services.currency import RateResult
from financetracker.services.iou import (
    BORROWING_CATEGORY_NAME,
    LENDING_CATEGORY_NAME,
    TransactionIouGuardError,
    close_unpaid,
    compute_open_iou_adjustment,
    create_payable,
    create_receivable,
    delete_transaction_with_iou_effects,
    ensure_borrowing_category,
    ensure_lending_category,
    guard_opening_transaction_amount_currency,
    record_repayment,
    reopen_unpaid,
    upcoming_iou_alerts,
    update_iou_metadata,
)
from financetracker.tests.factories import create_iou, create_transaction, create_user


def _constant_get_rates(rate, stale_date=None):
    def fake(keys):
        return {key: RateResult(rate=rate, stale_date=stale_date) for key in keys}

    return fake


class IouServiceTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_create_receivable_creates_expense_and_active_iou_atomically(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
            due_date=date(2026, 8, 1),
        )

        self.assertEqual(IOU.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(iou.direction, IOU.RECEIVABLE)
        self.assertEqual(iou.status, IOU.ACTIVE)
        self.assertEqual(iou.remaining_amount, Decimal("500.00"))
        self.assertEqual(iou.counterparty_name, "Jamie")
        self.assertEqual(iou.due_date, date(2026, 8, 1))

        opening = iou.opening_transaction
        self.assertEqual(opening.type, Transaction.EXPENSE)
        self.assertEqual(opening.amount, Decimal("500.00"))
        self.assertEqual(opening.currency, "CZK")
        self.assertEqual(opening.category.name, LENDING_CATEGORY_NAME)
        self.assertEqual(opening.category.type, Category.EXPENSE)
        self.assertIn("Jamie", opening.description)

    def test_ensure_lending_category_is_idempotent(self):
        first = ensure_lending_category()
        second = ensure_lending_category()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            Category.objects.filter(name=LENDING_CATEGORY_NAME, type=Category.EXPENSE).count(),
            1,
        )

    def test_compute_open_iou_adjustment_sums_active_receivables(self):
        create_iou(
            self.user,
            amount=Decimal("300.00"),
            currency="CZK",
            direction=IOU.RECEIVABLE,
            status=IOU.ACTIVE,
        )
        create_iou(
            self.user,
            amount=Decimal("200.00"),
            currency="CZK",
            direction=IOU.RECEIVABLE,
            status=IOU.ACTIVE,
        )
        create_iou(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
            direction=IOU.RECEIVABLE,
            status=IOU.PAID,
        )

        result = compute_open_iou_adjustment(self.user, "CZK")

        self.assertFalse(result.conversion_degraded)
        self.assertEqual(result.receivable_total, Decimal("500.00"))
        self.assertEqual(result.payable_total, Decimal("0"))
        self.assertEqual(result.net_adjustment, Decimal("500.00"))

    def test_lend_reduces_available_but_total_stays_at_pre_lend_level(self):
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
        )
        create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        from financetracker.services.display_conversion import convert_for_display

        display = convert_for_display(
            Transaction.objects.filter(user=self.user),
            "CZK",
        )
        adjustment = compute_open_iou_adjustment(self.user, "CZK")

        available = display.balance
        total = available + adjustment.net_adjustment

        self.assertEqual(available, Decimal("500.00"))
        self.assertEqual(total, Decimal("1000.00"))

    def test_compute_open_iou_adjustment_converts_foreign_currency_receivables(self):
        create_iou(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            direction=IOU.RECEIVABLE,
            status=IOU.ACTIVE,
        )

        with patch(
            "financetracker.services.iou.get_rates",
            side_effect=_constant_get_rates(Decimal("25.00")),
        ):
            result = compute_open_iou_adjustment(self.user, "CZK")

        self.assertFalse(result.conversion_degraded)
        self.assertEqual(result.net_adjustment, Decimal("250.00"))

    def test_compute_open_iou_adjustment_degrades_when_rate_missing(self):
        create_iou(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            direction=IOU.RECEIVABLE,
            status=IOU.ACTIVE,
        )

        with patch(
            "financetracker.services.iou.get_rates",
            return_value={},
        ):
            result = compute_open_iou_adjustment(self.user, "CZK")

        self.assertTrue(result.conversion_degraded)
        self.assertIsNone(result.net_adjustment)

    def test_create_payable_creates_income_and_active_iou_atomically(self):
        iou = create_payable(
            self.user,
            counterparty_name="Sam",
            amount=Decimal("300.00"),
            currency="CZK",
            due_date=date(2026, 9, 1),
        )

        self.assertEqual(IOU.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(iou.direction, IOU.PAYABLE)
        self.assertEqual(iou.status, IOU.ACTIVE)
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))
        self.assertEqual(iou.counterparty_name, "Sam")
        self.assertEqual(iou.due_date, date(2026, 9, 1))

        opening = iou.opening_transaction
        self.assertEqual(opening.type, Transaction.INCOME)
        self.assertEqual(opening.amount, Decimal("300.00"))
        self.assertEqual(opening.currency, "CZK")
        self.assertEqual(opening.category.name, BORROWING_CATEGORY_NAME)
        self.assertEqual(opening.category.type, Category.INCOME)
        self.assertIn("Sam", opening.description)

    def test_ensure_borrowing_category_is_idempotent(self):
        first = ensure_borrowing_category()
        second = ensure_borrowing_category()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            Category.objects.filter(name=BORROWING_CATEGORY_NAME, type=Category.INCOME).count(),
            1,
        )

    def test_compute_open_iou_adjustment_subtracts_active_payables(self):
        create_iou(
            self.user,
            amount=Decimal("400.00"),
            currency="CZK",
            direction=IOU.RECEIVABLE,
            status=IOU.ACTIVE,
        )
        create_iou(
            self.user,
            amount=Decimal("150.00"),
            currency="CZK",
            direction=IOU.PAYABLE,
            status=IOU.ACTIVE,
            opening_transaction=create_transaction(
                self.user,
                amount=Decimal("150.00"),
                currency="CZK",
                type=Transaction.INCOME,
            ),
        )
        create_iou(
            self.user,
            amount=Decimal("50.00"),
            currency="CZK",
            direction=IOU.PAYABLE,
            status=IOU.PAID,
            opening_transaction=create_transaction(
                self.user,
                amount=Decimal("50.00"),
                currency="CZK",
                type=Transaction.INCOME,
            ),
        )

        result = compute_open_iou_adjustment(self.user, "CZK")

        self.assertFalse(result.conversion_degraded)
        self.assertEqual(result.receivable_total, Decimal("400.00"))
        self.assertEqual(result.payable_total, Decimal("150.00"))
        self.assertEqual(result.net_adjustment, Decimal("250.00"))

    def test_partial_repayment_updates_available_total_and_remaining(self):
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
        )
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        record_repayment(iou, amount=Decimal("200.00"))

        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))
        self.assertEqual(iou.status, IOU.ACTIVE)

        repayment = iou.repayments.get()
        self.assertEqual(repayment.amount, Decimal("200.00"))
        self.assertEqual(repayment.transaction.type, Transaction.INCOME)
        self.assertEqual(repayment.transaction.category.name, LENDING_CATEGORY_NAME)
        self.assertIn("Jamie", repayment.transaction.description)

        from financetracker.services.display_conversion import convert_for_display

        display = convert_for_display(
            Transaction.objects.filter(user=self.user),
            "CZK",
        )
        adjustment = compute_open_iou_adjustment(self.user, "CZK")

        available = display.balance
        total = available + adjustment.net_adjustment

        self.assertEqual(available, Decimal("700.00"))
        self.assertEqual(total, Decimal("1000.00"))

    def test_full_repayment_closes_iou_as_paid(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        record_repayment(iou, amount=Decimal("500.00"))

        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("0"))
        self.assertEqual(iou.status, IOU.PAID)

        adjustment = compute_open_iou_adjustment(self.user, "CZK")
        self.assertEqual(adjustment.net_adjustment, Decimal("0"))

    def test_repayment_on_payable_creates_expense_with_borrowing_category(self):
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
        )
        iou = create_payable(
            self.user,
            counterparty_name="Sam",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        record_repayment(iou, amount=Decimal("200.00"))

        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))
        self.assertEqual(iou.status, IOU.ACTIVE)

        repayment = iou.repayments.get()
        self.assertEqual(repayment.transaction.type, Transaction.EXPENSE)
        self.assertEqual(repayment.transaction.category.name, BORROWING_CATEGORY_NAME)

        from financetracker.services.display_conversion import convert_for_display

        display = convert_for_display(
            Transaction.objects.filter(user=self.user),
            "CZK",
        )
        adjustment = compute_open_iou_adjustment(self.user, "CZK")

        available = display.balance
        total = available + adjustment.net_adjustment

        self.assertEqual(available, Decimal("1300.00"))
        self.assertEqual(total, Decimal("1000.00"))

    def test_repayment_cannot_exceed_remaining_amount(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        with self.assertRaises(ValueError):
            record_repayment(iou, amount=Decimal("500.01"))

    def _balances(self):
        from financetracker.services.display_conversion import convert_for_display

        display = convert_for_display(
            Transaction.objects.filter(user=self.user),
            "CZK",
        )
        adjustment = compute_open_iou_adjustment(self.user, "CZK")
        available = display.balance
        total = available + adjustment.net_adjustment
        return available, total

    def test_close_unpaid_transitions_status_and_drops_total_to_available(self):
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
        )
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("200.00"))
        iou.refresh_from_db()

        close_unpaid(iou)

        iou.refresh_from_db()
        self.assertEqual(iou.status, IOU.UNPAID)
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))

        available, total = self._balances()
        self.assertEqual(available, Decimal("700.00"))
        self.assertEqual(total, Decimal("700.00"))

    def test_reopen_unpaid_restores_total(self):
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
        )
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("200.00"))
        close_unpaid(iou)

        reopen_unpaid(iou)

        iou.refresh_from_db()
        self.assertEqual(iou.status, IOU.ACTIVE)
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))

        available, total = self._balances()
        self.assertEqual(available, Decimal("700.00"))
        self.assertEqual(total, Decimal("1000.00"))

    def test_close_unpaid_reopen_repay_to_paid_canonical_flow(self):
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
        )
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        available, total = self._balances()
        self.assertEqual(available, Decimal("500.00"))
        self.assertEqual(total, Decimal("1000.00"))

        record_repayment(iou, amount=Decimal("200.00"))
        iou.refresh_from_db()
        available, total = self._balances()
        self.assertEqual(available, Decimal("700.00"))
        self.assertEqual(total, Decimal("1000.00"))
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))

        close_unpaid(iou)
        iou.refresh_from_db()
        available, total = self._balances()
        self.assertEqual(iou.status, IOU.UNPAID)
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))
        self.assertEqual(available, Decimal("700.00"))
        self.assertEqual(total, Decimal("700.00"))

        reopen_unpaid(iou)
        record_repayment(iou, amount=Decimal("300.00"))

        iou.refresh_from_db()
        available, total = self._balances()
        self.assertEqual(iou.status, IOU.PAID)
        self.assertEqual(iou.remaining_amount, Decimal("0"))
        self.assertEqual(available, Decimal("1000.00"))
        self.assertEqual(total, Decimal("1000.00"))

    def test_close_unpaid_only_allowed_on_active_iou(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("500.00"))

        with self.assertRaises(ValueError):
            close_unpaid(iou)

    def test_reopen_unpaid_only_allowed_on_unpaid_iou(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("500.00"))

        with self.assertRaises(ValueError):
            reopen_unpaid(iou)

    def test_update_iou_metadata_on_active_iou(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
            due_date=date(2026, 8, 1),
        )

        updated = update_iou_metadata(
            iou,
            counterparty_name="James",
            due_date=date(2026, 9, 15),
        )

        self.assertEqual(updated.counterparty_name, "James")
        self.assertEqual(updated.due_date, date(2026, 9, 15))
        opening = iou.opening_transaction
        self.assertIn("Jamie", opening.description)

    def test_update_iou_metadata_rejected_on_closed_iou(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        close_unpaid(iou)

        with self.assertRaises(ValueError):
            update_iou_metadata(iou, counterparty_name="James")

    def test_borrow_increases_available_but_reduces_total(self):
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
        )
        create_payable(
            self.user,
            counterparty_name="Sam",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        from financetracker.services.display_conversion import convert_for_display

        display = convert_for_display(
            Transaction.objects.filter(user=self.user),
            "CZK",
        )
        adjustment = compute_open_iou_adjustment(self.user, "CZK")

        available = display.balance
        total = available + adjustment.net_adjustment

        self.assertEqual(available, Decimal("1500.00"))
        self.assertEqual(total, Decimal("1000.00"))


class IouLedgerGuardTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_delete_opening_transaction_blocked_while_iou_active(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        opening = iou.opening_transaction

        with self.assertRaises(TransactionIouGuardError):
            delete_transaction_with_iou_effects(opening)

        self.assertTrue(Transaction.objects.filter(pk=opening.pk).exists())
        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("500.00"))
        self.assertEqual(iou.status, IOU.ACTIVE)

    def test_guard_opening_transaction_amount_currency_blocked_while_iou_active(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        opening = iou.opening_transaction

        with self.assertRaises(TransactionIouGuardError):
            guard_opening_transaction_amount_currency(
                opening,
                amount=Decimal("400.00"),
                currency="CZK",
            )

        with self.assertRaises(TransactionIouGuardError):
            guard_opening_transaction_amount_currency(
                opening,
                amount=Decimal("500.00"),
                currency="EUR",
            )

        guard_opening_transaction_amount_currency(
            opening,
            amount=Decimal("500.00"),
            currency="CZK",
        )

    def test_delete_repayment_restores_remaining_amount_on_active_iou(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("200.00"))
        iou.refresh_from_db()
        repayment_tx = iou.repayments.get().transaction

        delete_transaction_with_iou_effects(repayment_tx)

        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("500.00"))
        self.assertEqual(iou.status, IOU.ACTIVE)
        self.assertFalse(Transaction.objects.filter(pk=repayment_tx.pk).exists())
        self.assertFalse(IOURepayment.objects.filter(iou=iou).exists())

    def test_delete_repayment_on_paid_iou_reopens_to_active(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("500.00"))
        iou.refresh_from_db()
        self.assertEqual(iou.status, IOU.PAID)
        repayment_tx = iou.repayments.get().transaction

        delete_transaction_with_iou_effects(repayment_tx)

        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("500.00"))
        self.assertEqual(iou.status, IOU.ACTIVE)

    def test_repayment_transactions_remain_when_iou_closed_as_unpaid(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("200.00"))
        close_unpaid(iou)
        repayment_tx = iou.repayments.get().transaction

        self.assertTrue(Transaction.objects.filter(pk=repayment_tx.pk).exists())
        self.assertEqual(iou.repayments.count(), 1)


class UpcomingIouAlertsTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.other_user = create_user(username="bob")
        self.today = date(2026, 7, 18)

    def test_includes_overdue_active_iou_with_due_date(self):
        overdue = create_iou(
            self.user,
            counterparty_name="Overdue",
            due_date=self.today - timedelta(days=3),
        )

        alerts = upcoming_iou_alerts(self.user, today=self.today)

        self.assertEqual([overdue], alerts)

    def test_includes_iou_due_within_seven_days(self):
        due_soon = create_iou(
            self.user,
            counterparty_name="Soon",
            due_date=self.today + timedelta(days=5),
        )
        create_iou(
            self.user,
            counterparty_name="Later",
            due_date=self.today + timedelta(days=8),
        )

        alerts = upcoming_iou_alerts(self.user, today=self.today)

        self.assertEqual([due_soon], alerts)

    def test_includes_iou_due_exactly_seven_days_out(self):
        on_window = create_iou(
            self.user,
            counterparty_name="Edge",
            due_date=self.today + timedelta(days=7),
        )

        alerts = upcoming_iou_alerts(self.user, today=self.today)

        self.assertEqual([on_window], alerts)

    def test_excludes_iou_without_due_date(self):
        create_iou(self.user, counterparty_name="Open ended", due_date=None)

        alerts = upcoming_iou_alerts(self.user, today=self.today)

        self.assertEqual(alerts, [])

    def test_excludes_closed_ious(self):
        create_iou(
            self.user,
            counterparty_name="Paid",
            due_date=self.today,
            status=IOU.PAID,
        )
        create_iou(
            self.user,
            counterparty_name="Unpaid",
            due_date=self.today,
            status=IOU.UNPAID,
        )

        alerts = upcoming_iou_alerts(self.user, today=self.today)

        self.assertEqual(alerts, [])

    def test_only_includes_signed_in_users_ious(self):
        mine = create_iou(
            self.user,
            counterparty_name="Mine",
            due_date=self.today,
        )
        create_iou(
            self.other_user,
            counterparty_name="Theirs",
            due_date=self.today,
        )

        alerts = upcoming_iou_alerts(self.user, today=self.today)

        self.assertEqual([mine], alerts)
