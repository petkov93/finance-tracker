from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from financetracker.models import Category, IOU, Transaction
from financetracker.services.currency import RateResult
from financetracker.services.iou import (
    LENDING_CATEGORY_NAME,
    compute_open_iou_adjustment,
    create_receivable,
    ensure_lending_category,
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
