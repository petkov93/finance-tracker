from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import IOU, Transaction, ensure_user_profile
from financetracker.services.currency import RateResult
from financetracker.services.iou import create_receivable
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
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

    def test_add_lend_creates_receivable_and_redirects(self):
        response = self.client.post(
            reverse("add_lend"),
            {
                "counterparty_name": "Jamie",
                "amount": "500.00",
                "currency": "CZK",
                "date": "2026-07-01",
                "due_date": "2026-08-01",
            },
        )

        self.assertRedirects(response, reverse("ious"))
        iou = IOU.objects.get(user=self.user)
        self.assertEqual(iou.counterparty_name, "Jamie")
        self.assertEqual(iou.remaining_amount, Decimal("500.00"))
        self.assertEqual(iou.opening_transaction.category.name, "Lending")

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

    def test_dashboard_degradation_hides_available_and_total(self):
        create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type=Transaction.INCOME,
            transaction_date=date.today(),
        )

        with patch(
            "financetracker.services.display_conversion.get_rates",
            return_value={},
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
