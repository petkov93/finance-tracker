from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import BankAccount, Transaction, UserProfile, ensure_user_profile
from financetracker.services.bank_accounts import ensure_cash_bank_account
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_category,
    create_transaction,
    create_user,
)

SUPPORTED = {"CZK": "Czech Koruna", "EUR": "Euro", "USD": "US Dollar"}


class TransactionCurrencyViewsTests(TestCase):
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
        self.cash = ensure_cash_bank_account(self.user)

    def _transaction_payload(self, **overrides):
        payload = {
            "type": Transaction.EXPENSE,
            "amount": "42.00",
            "currency": "CZK",
            "bank_account": self.cash.pk,
            "category": self.category.pk,
            "description": "Test",
            "date": "2025-01-15",
        }
        payload.update(overrides)
        return payload

    def _set_cash_currency(self, currency):
        """Test fixture helper — Bank account currency is immutable via model save."""
        BankAccount.objects.filter(pk=self.cash.pk).update(currency=currency)
        self.cash.refresh_from_db()

    def test_add_transaction_defaults_to_profile_currency(self):
        UserProfile.objects.filter(user=self.user).update(default_currency="EUR")
        self._set_cash_currency("EUR")

        response = self.client.get(reverse("add_transaction"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["currency"], "EUR")

        response = self.client.post(
            reverse("add_transaction"),
            self._transaction_payload(currency="EUR", description="Lunch"),
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction = Transaction.objects.get(user=self.user)
        self.assertEqual(transaction.currency, "EUR")

    def test_add_transaction_with_explicit_currency(self):
        self._set_cash_currency("USD")
        response = self.client.post(
            reverse("add_transaction"),
            self._transaction_payload(currency="USD", description="Salary"),
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction = Transaction.objects.get(user=self.user)
        self.assertEqual(transaction.currency, "USD")

    def test_edit_transaction_changes_currency(self):
        transaction = create_transaction(
            self.user,
            amount=Decimal("25.00"),
            description="Coffee",
            category=self.category,
            bank_account=self.cash,
        )
        Transaction.objects.filter(pk=transaction.pk).update(currency="CZK")
        self._set_cash_currency("EUR")

        response = self.client.get(reverse("edit_transaction", args=[transaction.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["currency"], "CZK")

        response = self.client.post(
            reverse("edit_transaction", args=[transaction.pk]),
            self._transaction_payload(
                currency="EUR",
                amount="25.00",
                description="Coffee",
                date=transaction.date.isoformat(),
            ),
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction.refresh_from_db()
        self.assertEqual(transaction.currency, "EUR")

    def test_invalid_currency_rejected(self):
        response = self.client.post(
            reverse("add_transaction"),
            self._transaction_payload(currency="XXX"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.assertIn("currency", response.context["form"].errors)
