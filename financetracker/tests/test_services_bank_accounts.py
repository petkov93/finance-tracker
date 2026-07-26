from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from financetracker.models import BankAccount, Transaction, UserProfile, ensure_user_profile
from financetracker.services.bank_accounts import (
    CASH_BANK_ACCOUNT_NAME,
    BankAccountError,
    assert_transaction_currency_matches_bank_account,
    bank_account_balance,
    bank_accounts_for_user,
    compute_available_balance,
    create_bank_account,
    delete_bank_account,
    ensure_cash_bank_account,
    ensure_user_bank_accounts,
    exclude_opening_balance_transactions,
    rename_bank_account,
)
from financetracker.services.currency import RateResult
from financetracker.tests.factories import create_transaction, create_user


def _constant_get_rates(rate, stale_date=None):
    def fake(keys):
        return {key: RateResult(rate=rate, stale_date=stale_date) for key in keys}

    return fake


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


class CreateBankAccountTests(TestCase):
    def test_create_bank_account_with_name_currency_kind_and_opening_balance(self):
        user = create_user()
        ensure_cash_bank_account(user)

        account = create_bank_account(
            user,
            name="ČSOB savings",
            currency="CZK",
            kind=BankAccount.SAVINGS,
            opening_balance=Decimal("1500.00"),
        )

        self.assertEqual(account.name, "ČSOB savings")
        self.assertEqual(account.currency, "CZK")
        self.assertEqual(account.kind, BankAccount.SAVINGS)
        self.assertFalse(account.is_cash)
        self.assertEqual(account.user_id, user.id)
        self.assertEqual(bank_account_balance(account), Decimal("1500.00"))

    def test_create_bank_account_kind_is_optional(self):
        user = create_user()
        ensure_cash_bank_account(user)

        account = create_bank_account(
            user,
            name="Revolut",
            currency="EUR",
            opening_balance=Decimal("0"),
        )

        self.assertEqual(account.kind, "")
        self.assertEqual(bank_account_balance(account), Decimal("0"))

    def test_opening_balance_zero_creates_no_opening_transaction(self):
        user = create_user()
        ensure_cash_bank_account(user)

        account = create_bank_account(
            user,
            name="Empty account",
            currency="CZK",
            opening_balance=Decimal("0"),
        )

        self.assertIsNone(account.opening_transaction)
        self.assertEqual(
            Transaction.objects.filter(bank_account=account).count(),
            0,
        )


class BankAccountBalanceTests(TestCase):
    def test_balance_includes_opening_balance_and_transactions(self):
        user = create_user()
        ensure_cash_bank_account(user)
        account = create_bank_account(
            user,
            name="Checking",
            currency="CZK",
            kind=BankAccount.CHECKING,
            opening_balance=Decimal("1000.00"),
        )
        create_transaction(
            user,
            amount=Decimal("200.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=account,
        )
        create_transaction(
            user,
            amount=Decimal("50.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            bank_account=account,
        )

        self.assertEqual(bank_account_balance(account), Decimal("1150.00"))

    def test_balance_may_be_negative(self):
        user = create_user()
        ensure_cash_bank_account(user)
        account = create_bank_account(
            user,
            name="Credit card",
            currency="CZK",
            kind=BankAccount.CREDIT,
            opening_balance=Decimal("-500.00"),
        )
        create_transaction(
            user,
            amount=Decimal("100.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            bank_account=account,
        )

        self.assertEqual(bank_account_balance(account), Decimal("-600.00"))


class RenameBankAccountTests(TestCase):
    def test_rename_custom_bank_account(self):
        user = create_user()
        ensure_cash_bank_account(user)
        account = create_bank_account(
            user,
            name="Old name",
            currency="CZK",
        )

        renamed = rename_bank_account(account, "New name")

        renamed.refresh_from_db()
        self.assertEqual(renamed.name, "New name")
        self.assertEqual(renamed.currency, "CZK")

    def test_currency_cannot_change_after_create(self):
        user = create_user()
        ensure_cash_bank_account(user)
        account = create_bank_account(
            user,
            name="Locked FX",
            currency="CZK",
        )

        account.currency = "EUR"
        with self.assertRaises(ValueError):
            account.save()

        account.refresh_from_db()
        self.assertEqual(account.currency, "CZK")


class DeleteBankAccountGuardTests(TestCase):
    def test_delete_blocked_when_transactions_exist(self):
        user = create_user()
        ensure_cash_bank_account(user)
        account = create_bank_account(
            user,
            name="In use",
            currency="CZK",
            opening_balance=Decimal("0"),
        )
        create_transaction(
            user,
            amount=Decimal("10.00"),
            currency="CZK",
            bank_account=account,
        )

        with self.assertRaises(BankAccountError):
            delete_bank_account(account)

        self.assertTrue(BankAccount.objects.filter(pk=account.pk).exists())

    def test_delete_blocked_when_opening_balance_linkage_exists(self):
        user = create_user()
        ensure_cash_bank_account(user)
        account = create_bank_account(
            user,
            name="With opening",
            currency="CZK",
            opening_balance=Decimal("100.00"),
        )

        with self.assertRaises(BankAccountError):
            delete_bank_account(account)

        self.assertTrue(BankAccount.objects.filter(pk=account.pk).exists())

    def test_empty_custom_bank_account_can_be_deleted(self):
        user = create_user()
        ensure_cash_bank_account(user)
        account = create_bank_account(
            user,
            name="Empty",
            currency="CZK",
            opening_balance=Decimal("0"),
        )

        delete_bank_account(account)

        self.assertFalse(BankAccount.objects.filter(pk=account.pk).exists())


class OpeningBalanceSpendingExclusionTests(TestCase):
    def test_opening_balance_excluded_from_spending_queryset(self):
        user = create_user()
        ensure_cash_bank_account(user)
        account = create_bank_account(
            user,
            name="Savings",
            currency="CZK",
            opening_balance=Decimal("1000.00"),
        )
        regular = create_transaction(
            user,
            amount=Decimal("40.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            bank_account=account,
        )

        qs = exclude_opening_balance_transactions(
            Transaction.objects.filter(user=user, bank_account=account)
        )

        self.assertQuerySetEqual(qs.order_by("pk"), [regular], transform=lambda t: t)


class AvailableBalanceTests(TestCase):
    def test_available_balance_sums_same_currency_bank_account_balances(self):
        user = create_user()
        ensure_user_profile(user)
        cash = ensure_cash_bank_account(user)
        create_transaction(
            user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=cash,
        )
        create_bank_account(
            user,
            name="Savings",
            currency="CZK",
            kind=BankAccount.SAVINGS,
            opening_balance=Decimal("500.00"),
        )

        result = compute_available_balance(user, "CZK")

        self.assertFalse(result.conversion_degraded)
        self.assertEqual(result.available, Decimal("1500.00"))

    def test_available_balance_display_converts_multi_currency_bank_accounts(self):
        user = create_user()
        ensure_user_profile(user)
        cash = ensure_cash_bank_account(user)
        create_transaction(
            user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=cash,
        )
        create_bank_account(
            user,
            name="Revolut",
            currency="EUR",
            opening_balance=Decimal("10.00"),
        )

        with patch(
            "financetracker.services.bank_accounts.get_rates",
            side_effect=_constant_get_rates(Decimal("25.00")),
        ):
            result = compute_available_balance(user, "CZK")

        self.assertFalse(result.conversion_degraded)
        # 1000 CZK + (10 EUR * 25) = 1250 CZK
        self.assertEqual(result.available, Decimal("1250.00"))

    def test_available_balance_degrades_when_bank_account_rate_unavailable(self):
        user = create_user()
        ensure_user_profile(user)
        ensure_cash_bank_account(user)
        create_bank_account(
            user,
            name="Revolut",
            currency="EUR",
            opening_balance=Decimal("10.00"),
        )

        with patch(
            "financetracker.services.bank_accounts.get_rates",
            return_value={},
        ):
            result = compute_available_balance(user, "CZK")

        self.assertTrue(result.conversion_degraded)
        self.assertIsNone(result.available)
