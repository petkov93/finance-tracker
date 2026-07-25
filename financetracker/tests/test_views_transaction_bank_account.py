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


class TransactionBankAccountViewsTests(TestCase):
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

    def test_add_transaction_defaults_bank_account_to_cash(self):
        response = self.client.get(reverse("add_transaction"))
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.fields["bank_account"].initial, self.cash.pk)

    def test_add_transaction_saves_selected_bank_account(self):
        response = self.client.post(
            reverse("add_transaction"),
            self._transaction_payload(description="Lunch"),
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction = Transaction.objects.get(user=self.user)
        self.assertEqual(transaction.bank_account_id, self.cash.id)

    def test_add_transaction_rejects_currency_mismatch(self):
        response = self.client.post(
            reverse("add_transaction"),
            self._transaction_payload(currency="USD"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.assertTrue(response.context["form"].errors)

    def test_edit_transaction_can_change_bank_account(self):
        other = BankAccount.objects.create(
            user=self.user,
            name="Revolut",
            currency="CZK",
            kind=BankAccount.CHECKING,
        )
        transaction = create_transaction(
            self.user,
            amount=Decimal("25.00"),
            currency="CZK",
            description="Coffee",
            category=self.category,
            bank_account=self.cash,
        )

        response = self.client.post(
            reverse("edit_transaction", args=[transaction.pk]),
            self._transaction_payload(
                bank_account=other.pk,
                amount="25.00",
                description="Coffee",
                date=transaction.date.isoformat(),
            ),
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction.refresh_from_db()
        self.assertEqual(transaction.bank_account_id, other.id)

    def test_edit_transaction_rejects_currency_mismatch(self):
        transaction = create_transaction(
            self.user,
            amount=Decimal("25.00"),
            currency="CZK",
            description="Coffee",
            category=self.category,
            bank_account=self.cash,
        )

        response = self.client.post(
            reverse("edit_transaction", args=[transaction.pk]),
            self._transaction_payload(
                currency="USD",
                amount="25.00",
                description="Coffee",
                date=transaction.date.isoformat(),
            ),
        )
        self.assertEqual(response.status_code, 200)
        transaction.refresh_from_db()
        self.assertEqual(transaction.currency, "CZK")
        self.assertTrue(response.context["form"].errors)


class AuthCashProvisioningTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)

    def test_register_creates_cash_with_default_currency(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newbie",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
                "default_currency": "EUR",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        profile = UserProfile.objects.get(user__username="newbie")
        cash = BankAccount.objects.get(user=profile.user, is_cash=True)
        self.assertEqual(cash.currency, "EUR")

    def test_login_ensures_cash_for_existing_user(self):
        user = create_user(username="oldie")
        ensure_user_profile(user)
        self.assertFalse(BankAccount.objects.filter(user=user).exists())

        response = self.client.post(
            reverse("login"),
            {"username": "oldie", "password": DEFAULT_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BankAccount.objects.filter(user=user, is_cash=True).exists())
