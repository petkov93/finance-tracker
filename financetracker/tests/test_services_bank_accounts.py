from decimal import Decimal

from django.test import TestCase

from financetracker.models import BankAccount, UserProfile, ensure_user_profile
from financetracker.services.bank_accounts import (
    CASH_BANK_ACCOUNT_NAME,
    BankAccountError,
    assert_transaction_currency_matches_bank_account,
    bank_accounts_for_user,
    delete_bank_account,
    ensure_cash_bank_account,
    ensure_user_bank_accounts,
)
from financetracker.tests.factories import create_transaction, create_user


class EnsureCashBankAccountTests(TestCase):
    def test_ensure_cash_creates_cash_with_default_currency(self):
        user = create_user()
        UserProfile.objects.create(user=user, default_currency="EUR")

        cash = ensure_cash_bank_account(user)

        self.assertEqual(cash.name, CASH_BANK_ACCOUNT_NAME)
        self.assertTrue(cash.is_cash)
        self.assertEqual(cash.currency, "EUR")
        self.assertEqual(cash.user_id, user.id)
        self.assertEqual(BankAccount.objects.filter(user=user, is_cash=True).count(), 1)

    def test_ensure_cash_is_idempotent(self):
        user = create_user()
        ensure_user_profile(user)

        first = ensure_cash_bank_account(user)
        second = ensure_cash_bank_account(user)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(BankAccount.objects.filter(user=user, is_cash=True).count(), 1)

    def test_ensure_cash_uses_profile_default_when_profile_missing(self):
        user = create_user()

        cash = ensure_cash_bank_account(user)

        profile = UserProfile.objects.get(user=user)
        self.assertEqual(cash.currency, profile.default_currency)


class EnsureUserBankAccountsTests(TestCase):
    def test_ensure_creates_cash_and_keeps_existing_assignments(self):
        user = create_user()
        ensure_user_profile(user)
        cash = ensure_cash_bank_account(user)
        other = BankAccount.objects.create(
            user=user,
            name="Savings",
            currency="CZK",
            kind=BankAccount.SAVINGS,
            is_cash=False,
        )
        assigned = create_transaction(
            user,
            amount=Decimal("10.00"),
            currency="CZK",
            bank_account=other,
        )

        ensured = ensure_user_bank_accounts(user)

        self.assertEqual(ensured.pk, cash.pk)
        assigned.refresh_from_db()
        self.assertEqual(assigned.bank_account_id, other.id)

    def test_bank_accounts_for_user_ensures_cash_and_lists_accounts(self):
        user = create_user()
        ensure_user_profile(user)

        accounts = list(bank_accounts_for_user(user))

        self.assertEqual(len(accounts), 1)
        self.assertTrue(accounts[0].is_cash)
        self.assertEqual(str(accounts[0]), f"Cash (CZK) — {user.username}")


class CashDeleteGuardTests(TestCase):
    def test_cash_cannot_be_deleted_via_service(self):
        user = create_user()
        cash = ensure_cash_bank_account(user)

        with self.assertRaises(BankAccountError):
            delete_bank_account(cash)

        self.assertTrue(BankAccount.objects.filter(pk=cash.pk).exists())

    def test_cash_cannot_be_deleted_via_model(self):
        user = create_user()
        cash = ensure_cash_bank_account(user)

        with self.assertRaises(ValueError):
            cash.delete()

        self.assertTrue(BankAccount.objects.filter(pk=cash.pk).exists())

    def test_cash_cannot_be_deleted_via_queryset(self):
        user = create_user()
        cash = ensure_cash_bank_account(user)

        with self.assertRaises(ValueError):
            BankAccount.objects.filter(pk=cash.pk).delete()

        self.assertTrue(BankAccount.objects.filter(pk=cash.pk).exists())

    def test_non_cash_bank_account_can_be_deleted(self):
        user = create_user()
        ensure_cash_bank_account(user)
        savings = BankAccount.objects.create(
            user=user,
            name="Savings",
            currency="CZK",
            kind=BankAccount.SAVINGS,
            is_cash=False,
        )

        delete_bank_account(savings)

        self.assertFalse(BankAccount.objects.filter(pk=savings.pk).exists())

    def test_non_cash_bank_account_can_be_deleted_via_queryset(self):
        user = create_user()
        ensure_cash_bank_account(user)
        savings = BankAccount.objects.create(
            user=user,
            name="Savings",
            currency="CZK",
            kind=BankAccount.SAVINGS,
            is_cash=False,
        )

        BankAccount.objects.filter(pk=savings.pk).delete()

        self.assertFalse(BankAccount.objects.filter(pk=savings.pk).exists())


class TransactionCurrencyMatchTests(TestCase):
    def test_matching_currency_is_allowed(self):
        user = create_user()
        cash = ensure_cash_bank_account(user)

        assert_transaction_currency_matches_bank_account(
            currency=cash.currency,
            bank_account=cash,
        )

    def test_mismatching_currency_is_rejected(self):
        user = create_user()
        cash = ensure_cash_bank_account(user)

        with self.assertRaises(BankAccountError):
            assert_transaction_currency_matches_bank_account(
                currency="USD",
                bank_account=cash,
            )
