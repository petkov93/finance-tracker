from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import IOU, Transaction, UserProfile, ensure_user_profile
from financetracker.services.iou import create_receivable, record_repayment
from financetracker.services.currency import RateResult
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_category,
    create_transaction,
    create_user,
)

SUPPORTED = {"CZK": "Czech Koruna", "EUR": "Euro", "USD": "US Dollar"}


def _constant_get_rates(rate, stale_date=None):
    def fake(keys):
        return {key: RateResult(rate=rate, stale_date=stale_date) for key in keys}

    return fake


class TransactionViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.other_user = create_user(username="bob")
        self.category = create_category()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)
        ensure_user_profile(self.user)
        ensure_user_profile(self.other_user)

    def test_add_transaction(self):
        response = self.client.post(
            reverse("add_transaction"),
            {
                "type": Transaction.INCOME,
                "amount": "1500.50",
                "currency": "CZK",
                "category": self.category.pk,
                "description": "Salary",
                "date": "2025-01-15",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction = Transaction.objects.get(user=self.user)
        self.assertEqual(transaction.amount, Decimal("1500.50"))
        self.assertEqual(transaction.type, Transaction.INCOME)
        self.assertEqual(transaction.description, "Salary")

    def test_edit_transaction(self):
        transaction = create_transaction(
            self.user,
            amount=Decimal("50.00"),
            description="Lunch",
            category=self.category,
        )
        response = self.client.post(
            reverse("edit_transaction", args=[transaction.pk]),
            {
                "type": Transaction.EXPENSE,
                "amount": "75.00",
                "currency": "CZK",
                "category": self.category.pk,
                "description": "Updated lunch",
                "date": transaction.date.isoformat(),
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction.refresh_from_db()
        self.assertEqual(transaction.amount, Decimal("75.00"))
        self.assertEqual(transaction.description, "Updated lunch")

    def test_delete_transaction(self):
        transaction = create_transaction(self.user)
        response = self.client.post(reverse("delete_transaction", args=[transaction.pk]))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(Transaction.objects.filter(pk=transaction.pk).exists())

    def test_dashboard_balance_calculation(self):
        create_transaction(self.user, amount=Decimal("1000.00"), type=Transaction.INCOME)
        create_transaction(self.user, amount=Decimal("250.00"), type=Transaction.EXPENSE)
        create_transaction(self.user, amount=Decimal("100.00"), type=Transaction.EXPENSE)

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income"], Decimal("1000.00"))
        self.assertEqual(response.context["total_expense"], Decimal("350.00"))
        self.assertEqual(response.context["available"], Decimal("650.00"))
        self.assertEqual(response.context["total"], Decimal("650.00"))

    def test_dashboard_category_filter(self):
        food = create_category(name="Food")
        transport = create_category(name="Transport")
        food_tx = create_transaction(self.user, category=food, description="Groceries")
        create_transaction(self.user, category=transport, description="Bus")

        response = self.client.get(reverse("dashboard"), {"category": food.pk})
        rows = list(response.context["display_transactions"])
        self.assertEqual([row.transaction for row in rows], [food_tx])

    def test_dashboard_search_filter(self):
        food = create_category(name="Food")
        matching = create_transaction(self.user, category=food, description="Groceries")
        create_transaction(self.user, description="Rent payment")

        response = self.client.get(reverse("dashboard"), {"q": "food"})
        rows = list(response.context["display_transactions"])
        self.assertEqual([row.transaction for row in rows], [matching])

    def test_dashboard_converted_totals_with_mixed_currencies(self):
        past = date.today() - timedelta(days=7)
        UserProfile.objects.filter(user=self.user).update(default_currency="CZK")
        create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type=Transaction.INCOME,
            transaction_date=past,
        )
        create_transaction(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            transaction_date=past,
        )

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_constant_get_rates(Decimal("25.00")),
        ):
            response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["total_income"], Decimal("250.00"))
        self.assertEqual(response.context["total_expense"], Decimal("100.00"))
        self.assertEqual(response.context["available"], Decimal("150.00"))
        self.assertEqual(response.context["total"], Decimal("150.00"))

    def test_dashboard_dual_amount_display_for_foreign_currency(self):
        past = date.today() - timedelta(days=7)
        UserProfile.objects.filter(user=self.user).update(default_currency="CZK")
        create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            transaction_date=past,
        )

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_constant_get_rates(Decimal("25.00")),
        ):
            response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "250.00 CZK")
        self.assertContains(response, "10.00 EUR")
        self.assertContains(response, "transaction-amount-footnote")

    def test_dashboard_formats_amounts_for_accept_language(self):
        past = date.today() - timedelta(days=7)
        UserProfile.objects.filter(user=self.user).update(default_currency="CZK")
        create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type=Transaction.INCOME,
            transaction_date=past,
        )

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_constant_get_rates(Decimal("25.00")),
        ):
            response = self.client.get(
                reverse("dashboard"),
                HTTP_ACCEPT_LANGUAGE="cs-CZ,cs;q=0.9",
            )

        self.assertEqual(response.context["display_locale"], "cs")
        self.assertContains(response, "250,00 CZK")
        self.assertContains(response, "10,00 EUR")

    def test_dashboard_single_amount_display_for_same_currency(self):
        create_transaction(self.user, amount=Decimal("100.00"), currency="CZK")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "100.00 CZK")
        self.assertNotContains(response, "transaction-amount-footnote")

    def test_dashboard_filter_applies_before_conversion(self):
        food = create_category(name="Food")
        past = date.today() - timedelta(days=7)
        UserProfile.objects.filter(user=self.user).update(default_currency="CZK")
        food_tx = create_transaction(
            self.user,
            category=food,
            amount=Decimal("10.00"),
            currency="EUR",
            description="Groceries",
            transaction_date=past,
        )
        create_transaction(
            self.user,
            amount=Decimal("50.00"),
            currency="EUR",
            description="Rent",
            transaction_date=past,
        )

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_constant_get_rates(Decimal("25.00")),
        ):
            response = self.client.get(reverse("dashboard"), {"category": food.pk})

        rows = list(response.context["display_transactions"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].transaction, food_tx)
        self.assertEqual(rows[0].primary_amount, Decimal("250.00"))

    def test_dashboard_degradation_shows_warning_and_transaction_currency_amounts(self):
        UserProfile.objects.filter(user=self.user).update(default_currency="CZK")
        create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
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
        self.assertContains(response, "Exchange rates are unavailable")
        self.assertContains(response, "10.00 EUR")
        self.assertNotContains(response, "hero-stats--balances")

    def test_dashboard_stale_rates_show_info_banner_and_totals(self):
        UserProfile.objects.filter(user=self.user).update(default_currency="CZK")
        yesterday = date.today() - timedelta(days=1)
        create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type="income",
            transaction_date=date.today(),
        )

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_constant_get_rates(Decimal("25.00"), stale_date=yesterday),
        ):
            response = self.client.get(reverse("dashboard"))

        self.assertFalse(response.context["conversion_degraded"])
        self.assertEqual(response.context["rates_stale_date"], yesterday)
        self.assertEqual(response.context["available"], Decimal("250.00"))
        self.assertEqual(response.context["total"], Decimal("250.00"))
        self.assertContains(response, "Exchange rates from")
        self.assertContains(response, yesterday.isoformat())
        self.assertContains(response, "hero-stats")

    def test_user_cannot_edit_other_users_transaction(self):
        other_transaction = create_transaction(self.other_user)
        response = self.client.get(reverse("edit_transaction", args=[other_transaction.pk]))
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_delete_other_users_transaction(self):
        other_transaction = create_transaction(self.other_user)
        response = self.client.post(reverse("delete_transaction", args=[other_transaction.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Transaction.objects.filter(pk=other_transaction.pk).exists())


class IouLinkedTransactionViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.category = create_category()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)
        ensure_user_profile(self.user)

    def test_delete_opening_transaction_blocked_from_dashboard(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        opening = iou.opening_transaction

        response = self.client.post(reverse("delete_transaction", args=[opening.pk]))

        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(Transaction.objects.filter(pk=opening.pk).exists())

    def test_edit_opening_transaction_blocked_from_dashboard(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        opening = iou.opening_transaction

        response = self.client.get(reverse("edit_transaction", args=[opening.pk]))

        self.assertRedirects(response, reverse("dashboard"))
        opening.refresh_from_db()
        self.assertEqual(opening.amount, Decimal("500.00"))

    def test_delete_repayment_blocked_from_dashboard(self):
        iou = create_receivable(
            self.user,
            counterparty_name="Jamie",
            amount=Decimal("500.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("200.00"))
        iou.refresh_from_db()
        repayment_tx = iou.repayments.get().transaction

        response = self.client.post(reverse("delete_transaction", args=[repayment_tx.pk]))

        self.assertRedirects(response, reverse("dashboard"))
        iou.refresh_from_db()
        self.assertEqual(iou.remaining_amount, Decimal("300.00"))
        self.assertTrue(Transaction.objects.filter(pk=repayment_tx.pk).exists())
