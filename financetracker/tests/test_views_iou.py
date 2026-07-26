from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import IOU, Transaction, ensure_user_profile
from financetracker.services.bank_accounts import ensure_cash_bank_account
from financetracker.services.currency import RateResult
from financetracker.services.iou import close_unpaid, create_payable, create_receivable
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_bank_account,
    create_iou,
    create_transaction,
    create_user,
)

SUPPORTED = {"CZK": "Czech Koruna", "EUR": "Euro", "USD": "US Dollar"}


def _constant_get_rates(rate, stale_date=None):
    def fake(keys):
        return {key: RateResult(rate=rate, stale_date=stale_date) for key in keys}

    return fake


class IouViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.other_user = create_user(username="bob")
        ensure_user_profile(self.user)
        ensure_user_profile(self.other_user)
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)

    def test_ious_lists_only_active_receivables_for_signed_in_user(self):
        create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("200.00"),
            currency="CZK",
        )
        create_iou(
            self.other_user,
            counterparty_name="Other",
            amount=Decimal("999.00"),
            currency="CZK",
        )
        create_iou(
            self.user,
            counterparty_name="Closed",
            amount=Decimal("50.00"),
            currency="CZK",
            status=IOU.PAID,
        )

        response = self.client.get(reverse("ious"))

        self.assertEqual(response.status_code, 200)
        receivables = list(response.context["receivables"])
        self.assertEqual(len(receivables), 1)
        self.assertEqual(receivables[0].counterparty_name, "Jamie")

    def test_ious_lists_only_active_payables_for_signed_in_user(self):
        create_payable(
            self.user,
            counterparty_name="Sam",
            amount=Decimal("300.00"),
            currency="CZK",
        )
        create_iou(
            self.other_user,
            counterparty_name="Other",
            amount=Decimal("999.00"),
            currency="CZK",
            direction=IOU.PAYABLE,
            opening_transaction=create_transaction(
                self.other_user,
                amount=Decimal("999.00"),
                currency="CZK",
                type=Transaction.INCOME,
            ),
        )
        create_iou(
            self.user,
            counterparty_name="Closed",
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

        response = self.client.get(reverse("ious"))

        self.assertEqual(response.status_code, 200)
        payables = list(response.context["payables"])
        self.assertEqual(len(payables), 1)
        self.assertEqual(payables[0].counterparty_name, "Sam")
        self.assertContains(response, "Active payables")
        self.assertContains(response, "Borrowed")

    def test_add_lend_form_defaults_bank_account_to_cash(self):
        cash = ensure_cash_bank_account(self.user)

        response = self.client.get(reverse("add_lend"))

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.fields["bank_account"].initial, cash.pk)
        self.assertContains(response, "Bank account")
        self.assertContains(response, f'value="{cash.pk}"')

    def test_add_lend_creates_receivable_and_redirects(self):
        cash = ensure_cash_bank_account(self.user)
        response = self.client.post(
            reverse("add_lend"),
            {
                "counterparty_name": "Jamie",
                "amount": "500.00",
                "currency": "CZK",
                "bank_account": str(cash.pk),
                "date": "2026-07-01",
                "due_date": "2026-08-01",
            },
        )

        self.assertRedirects(response, reverse("ious"))
        iou = IOU.objects.get(
            user=self.user,
            direction=IOU.RECEIVABLE,
            counterparty_name="Jamie",
        )
        self.assertEqual(iou.opening_transaction.bank_account, cash)

    def test_add_lend_assigns_opening_transaction_to_chosen_bank_account(self):
        savings = create_bank_account(
            self.user,
            name="Savings",
            currency="CZK",
        )

        response = self.client.post(
            reverse("add_lend"),
            {
                "counterparty_name": "Jamie",
                "amount": "500.00",
                "currency": "CZK",
                "bank_account": str(savings.pk),
                "date": "2026-07-01",
            },
        )

        self.assertRedirects(response, reverse("ious"))
        iou = IOU.objects.get(user=self.user, counterparty_name="Jamie")
        self.assertEqual(iou.opening_transaction.bank_account, savings)

    def test_add_borrow_creates_payable_and_redirects(self):
        cash = ensure_cash_bank_account(self.user)
        response = self.client.post(
            reverse("add_borrow"),
            {
                "counterparty_name": "Sam",
                "amount": "300.00",
                "currency": "CZK",
                "bank_account": str(cash.pk),
                "date": "2026-07-01",
                "due_date": "2026-09-01",
            },
        )

        self.assertRedirects(response, reverse("ious"))
        iou = IOU.objects.get(
            user=self.user,
            direction=IOU.PAYABLE,
            counterparty_name="Sam",
        )
        self.assertEqual(iou.opening_transaction.bank_account, cash)

    def test_dashboard_exposes_available_and_total_context_keys(self):
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

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["available"], Decimal("500.00"))
        self.assertEqual(response.context["total"], Decimal("1000.00"))

    def test_dashboard_total_reflects_open_payables(self):
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

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["available"], Decimal("1500.00"))
        self.assertEqual(response.context["total"], Decimal("1000.00"))

    def test_dashboard_degradation_hides_available_and_total(self):
        eur_account = create_bank_account(
            self.user,
            name="Revolut",
            currency="EUR",
        )
        create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type=Transaction.INCOME,
            transaction_date=date.today(),
            bank_account=eur_account,
        )

        with (
            patch(
                "financetracker.services.display_conversion.get_rates",
                return_value={},
            ),
            patch(
                "financetracker.services.bank_accounts.get_rates",
                return_value={},
            ),
        ):
            response = self.client.get(reverse("dashboard"))

        self.assertTrue(response.context["conversion_degraded"])
        self.assertIsNone(response.context["available"])
        self.assertIsNone(response.context["total"])
        self.assertNotContains(response, "hero-stats--balances")

    def test_ious_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("ious"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_sidebar_contains_ious_link(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, reverse("ious"))
        self.assertContains(response, ">IOUs<")

    def test_dashboard_shows_iou_alerts_strip_when_due_soon(self):
        create_iou(
            self.user,
            counterparty_name="Jamie",
            due_date=date.today() + timedelta(days=3),
        )

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "IOUs due soon or overdue")
        self.assertContains(response, "Jamie")

    def test_dashboard_hides_iou_alerts_strip_when_none_due(self):
        create_iou(
            self.user,
            counterparty_name="Later",
            due_date=date.today() + timedelta(days=30),
        )

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "IOUs due soon or overdue")

    def test_sidebar_badge_matches_iou_alert_count(self):
        create_iou(
            self.user,
            counterparty_name="One",
            due_date=date.today(),
        )
        create_iou(
            self.user,
            counterparty_name="Two",
            due_date=date.today() + timedelta(days=2),
        )
        create_iou(
            self.user,
            counterparty_name="Later",
            due_date=date.today() + timedelta(days=30),
        )

        response = self.client.get(reverse("statistics"))

        self.assertContains(response, 'class="sidebar-badge"')
        self.assertContains(response, 'aria-label="2 IOU due soon"')
        self.assertContains(response, ">2<")

    def test_iou_detail_shows_opening_and_repayment_transactions(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        response = self.client.get(reverse("iou_detail", args=[iou.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jamie")
        self.assertContains(response, "Linked transactions")
        self.assertContains(response, "Lent to Jamie")
        self.assertContains(response, "Record repayment")

    def test_iou_detail_repay_form_defaults_bank_account_to_cash(self):
        cash = ensure_cash_bank_account(self.user)
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        response = self.client.get(reverse("iou_detail", args=[iou.pk]))

        form = response.context["repay_form"]
        self.assertEqual(form.fields["bank_account"].initial, cash.pk)
        self.assertContains(response, "Bank account")

    def test_iou_detail_isolated_to_owner(self):
        iou = create_receivable(
            self.other_user,
            counterparty_name="Theirs",
            amount=Decimal("100.00"),
            currency="CZK",
        )

        response = self.client.get(reverse("iou_detail", args=[iou.pk]))

        self.assertEqual(response.status_code, 404)

    def test_repay_partial_updates_remaining_and_dashboard_balances(self):
        cash = ensure_cash_bank_account(self.user)
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

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "amount": "200.00",
                "date": "2026-07-10",
                "bank_account": str(cash.pk),
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))
        self.assertEqual(iou.status, IOU.ACTIVE)
        self.assertEqual(iou.repayments.count(), 1)
        self.assertEqual(iou.repayments.get().transaction.bank_account, cash)

        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.context["available"], Decimal("700.00"))
        self.assertEqual(dashboard.context["total"], Decimal("1000.00"))

        detail = self.client.get(reverse("iou_detail", args=[iou.pk]))
        self.assertContains(detail, "Repayment from Jamie")
        self.assertContains(detail, "200.00")

    def test_repay_assigns_transaction_to_chosen_bank_account(self):
        savings = create_bank_account(
            self.user,
            name="Savings",
            currency="CZK",
        )
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "repay",
                "amount": "200.00",
                "date": "2026-07-10",
                "bank_account": str(savings.pk),
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        repayment = iou.repayments.get()
        self.assertEqual(repayment.transaction.bank_account, savings)

    def test_repay_full_closes_iou_as_paid(self):
        cash = ensure_cash_bank_account(self.user)
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "amount": "500.00",
                "date": "2026-07-10",
                "bank_account": str(cash.pk),
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        iou.refresh_from_db()
        self.assertEqual(iou.status, IOU.PAID)
        self.assertEqual(iou.remaining_amount, Decimal("0"))

        detail = self.client.get(reverse("iou_detail", args=[iou.pk]))
        self.assertNotContains(detail, "Record repayment")

    def test_repay_rejects_amount_over_remaining(self):
        cash = ensure_cash_bank_account(self.user)
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "amount": "500.01",
                "date": "2026-07-10",
                "bank_account": str(cash.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("500.00"))
        self.assertEqual(iou.repayments.count(), 0)

    @patch(
        "financetracker.views.record_repayment",
        side_effect=ValueError("Repayment amount cannot exceed remaining amount."),
    )
    def test_repay_surfaces_service_rejection_instead_of_500(self, _mock_record):
        cash = ensure_cash_bank_account(self.user)
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "repay",
                "amount": "200.00",
                "date": "2026-07-10",
                "bank_account": str(cash.pk),
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        messages = [m.message for m in get_messages(response.wsgi_request)]
        self.assertIn("Repayment amount cannot exceed remaining amount.", messages)
        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("500.00"))
        self.assertEqual(iou.repayments.count(), 0)

    def test_close_unpaid_from_detail_updates_status_and_dashboard_total(self):
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
        self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {"amount": "200.00", "date": "2026-07-10", "action": "repay", "bank_account": str(ensure_cash_bank_account(self.user).pk)},
        )
        iou.refresh_from_db()

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {"action": "close_unpaid"},
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        iou.refresh_from_db()
        self.assertEqual(iou.status, IOU.UNPAID)
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))

        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.context["available"], Decimal("700.00"))
        self.assertEqual(dashboard.context["total"], Decimal("700.00"))

    def test_reopen_unpaid_from_detail_restores_dashboard_total(self):
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
        self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {"amount": "200.00", "date": "2026-07-10", "action": "repay", "bank_account": str(ensure_cash_bank_account(self.user).pk)},
        )
        close_unpaid(iou)

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {"action": "reopen"},
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        iou.refresh_from_db()
        self.assertEqual(iou.status, IOU.ACTIVE)

        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.context["available"], Decimal("700.00"))
        self.assertEqual(dashboard.context["total"], Decimal("1000.00"))

        detail = self.client.get(reverse("iou_detail", args=[iou.pk]))
        self.assertContains(detail, "Reopen IOU", count=0)
        self.assertContains(detail, "Close as unpaid")

    def test_edit_metadata_on_active_iou(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
            due_date=date(2026, 8, 1),
        )

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "edit_metadata",
                "counterparty_name": "James",
                "due_date": "2026-09-15",
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        iou.refresh_from_db()
        self.assertEqual(iou.counterparty_name, "James")
        self.assertEqual(iou.due_date, date(2026, 9, 15))

    def test_paid_iou_cannot_be_reopened_or_edited(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {"amount": "500.00", "date": "2026-07-10", "action": "repay", "bank_account": str(ensure_cash_bank_account(self.user).pk)},
        )
        iou.refresh_from_db()
        self.assertEqual(iou.status, IOU.PAID)

        reopen = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {"action": "reopen"},
        )
        self.assertRedirects(reopen, reverse("iou_detail", args=[iou.pk]))

        edit = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "edit_metadata",
                "counterparty_name": "James",
            },
        )
        self.assertRedirects(edit, reverse("iou_detail", args=[iou.pk]))

        iou.refresh_from_db()
        self.assertEqual(iou.counterparty_name, "Jamie")
        self.assertEqual(iou.status, IOU.PAID)

        detail = self.client.get(reverse("iou_detail", args=[iou.pk]))
        self.assertNotContains(detail, "Edit details")
        self.assertNotContains(detail, "Reopen IOU")

    def test_ious_page_shows_collapsible_closed_section_with_unpaid_missing_amount(self):
        create_receivable(
            self.user,
            counterparty_name="Active",
            amount=Decimal("100.00"),
            currency="CZK",
        )
        unpaid = create_receivable(
            self.user,
            counterparty_name="Written off",
            amount=Decimal("300.00"),
            currency="CZK",
        )
        close_unpaid(unpaid)
        paid = create_receivable(
            self.user,
            counterparty_name="Settled",
            amount=Decimal("50.00"),
            currency="CZK",
        )
        self.client.post(
            reverse("iou_detail", args=[paid.pk]),
            {"amount": "50.00", "date": "2026-07-10", "action": "repay", "bank_account": str(ensure_cash_bank_account(self.user).pk)},
        )

        response = self.client.get(reverse("ious"))

        self.assertContains(response, "Closed (2)")
        self.assertContains(response, "Written off")
        self.assertContains(response, "300.00")
        self.assertContains(response, "missing")
        self.assertContains(response, "Settled")
        receivables = list(response.context["receivables"])
        self.assertEqual(len(receivables), 1)
        self.assertEqual(receivables[0].counterparty_name, "Active")


class IouPolishViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        ensure_user_profile(self.user)
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)

    def test_dashboard_hides_edit_for_iou_linked_transactions(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        opening = iou.opening_transaction

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(
            response,
            f'href="{reverse("edit_transaction", args=[opening.pk])}"',
        )

    def test_dashboard_spending_pills_exclude_iou_amounts(self):
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

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["total_income"], Decimal("1000.00"))
        self.assertEqual(response.context["total_expense"], Decimal("0"))
        self.assertEqual(response.context["available"], Decimal("500.00"))

    def test_edit_repayment_from_iou_detail_updates_remaining(self):
        euro_pot = create_bank_account(self.user, name="Euro", currency="EUR")
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("5.00"),
            currency="EUR",
            bank_account=euro_pot,
        )
        self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "repay",
                "amount": "3.00",
                "date": "2026-07-10",
                "bank_account": str(euro_pot.pk),
            },
        )
        repayment = iou.repayments.get()

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "edit_repayment",
                "repayment_id": repayment.pk,
                "amount": "2.00",
                "date": "2026-07-11",
                "bank_account": str(euro_pot.pk),
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("3.00"))

    @patch(
        "financetracker.views.update_repayment",
        side_effect=ValueError("Repayment amount cannot exceed remaining amount."),
    )
    def test_edit_repayment_surfaces_service_rejection_instead_of_500(
        self, _mock_update
    ):
        euro_pot = create_bank_account(self.user, name="Euro", currency="EUR")
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("5.00"),
            currency="EUR",
            bank_account=euro_pot,
        )
        self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "repay",
                "amount": "3.00",
                "date": "2026-07-10",
                "bank_account": str(euro_pot.pk),
            },
        )
        repayment = iou.repayments.get()

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "edit_repayment",
                "repayment_id": repayment.pk,
                "amount": "2.00",
                "date": "2026-07-11",
                "bank_account": str(euro_pot.pk),
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        messages = [m.message for m in get_messages(response.wsgi_request)]
        self.assertIn("Repayment amount cannot exceed remaining amount.", messages)
        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("2.00"))

    def test_delete_repayment_from_iou_detail(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {"action": "repay", "amount": "200.00", "date": "2026-07-10", "bank_account": str(ensure_cash_bank_account(self.user).pk)},
        )
        repayment = iou.repayments.get()

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "delete_repayment",
                "repayment_id": repayment.pk,
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("500.00"))
        self.assertEqual(iou.repayments.count(), 0)

    def test_delete_repayment_on_paid_iou_available_from_detail(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {"action": "repay", "amount": "500.00", "date": "2026-07-10", "bank_account": str(ensure_cash_bank_account(self.user).pk)},
        )
        repayment = iou.repayments.get()

        detail = self.client.get(reverse("iou_detail", args=[iou.pk]))
        self.assertContains(detail, "Paid")
        self.assertContains(detail, "Delete repayment")

        response = self.client.post(
            reverse("iou_detail", args=[iou.pk]),
            {
                "action": "delete_repayment",
                "repayment_id": repayment.pk,
            },
        )

        self.assertRedirects(response, reverse("iou_detail", args=[iou.pk]))
        reopened = self.client.get(reverse("iou_detail", args=[iou.pk]))
        self.assertContains(reopened, "Active")
        self.assertNotContains(reopened, "Delete repayment")

    def test_clear_finished_ious_from_settings(self):
        paid = create_receivable(
            self.user,
            counterparty_name="Settled",
            amount=Decimal("50.00"),
            currency="CZK",
        )
        self.client.post(
            reverse("iou_detail", args=[paid.pk]),
            {"action": "repay", "amount": "50.00", "date": "2026-07-10", "bank_account": str(ensure_cash_bank_account(self.user).pk)},
        )
        paid.refresh_from_db()
        paid_opening_id = paid.opening_transaction_id
        paid_repayment_id = paid.repayments.get().transaction_id
        unpaid = create_receivable(
            self.user,
            counterparty_name="Written off",
            amount=Decimal("100.00"),
            currency="CZK",
        )
        close_unpaid(unpaid)

        response = self.client.post(reverse("clear_finished_ious"))

        self.assertRedirects(response, reverse("settings"))
        self.assertFalse(IOU.objects.filter(counterparty_name="Settled").exists())
        self.assertTrue(IOU.objects.filter(counterparty_name="Written off").exists())
        self.assertFalse(Transaction.objects.filter(pk=paid_opening_id).exists())
        self.assertFalse(Transaction.objects.filter(pk=paid_repayment_id).exists())

    def test_add_transaction_form_excludes_lending_and_borrowing_categories(self):
        create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("100.00"),
            currency="CZK",
        )
        create_payable(
            self.user,
            counterparty_name="Sam",
            amount=Decimal("50.00"),
            currency="CZK",
        )

        response = self.client.get(reverse("add_transaction"))

        category_names = {c.name for c in response.context["all_categories"]}
        self.assertNotIn("Lending", category_names)
        self.assertNotIn("Borrowing", category_names)
        self.assertNotContains(response, "Lending")
        self.assertNotContains(response, "Borrowing")
