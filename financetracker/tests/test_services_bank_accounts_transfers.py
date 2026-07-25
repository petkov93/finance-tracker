from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from financetracker.models import Transaction, Transfer
from financetracker.services.bank_accounts import (
    BankAccountError,
    bank_account_balance,
    create_bank_account,
    create_transfer,
    delete_transfer,
    ensure_cash_bank_account,
    exclude_from_spending_statistics,
    update_transfer,
)
from financetracker.services.rate_source import CurrencyConversionError
from financetracker.tests.factories import create_transaction, create_user


class SameCurrencyTransferTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.cash = ensure_cash_bank_account(self.user)
        self.savings = create_bank_account(
            self.user,
            name="Savings",
            currency="CZK",
        )
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=self.cash,
        )

    def test_same_currency_transfer_debits_source_and_credits_destination(self):
        transfer = create_transfer(
            self.user,
            from_bank_account=self.cash,
            to_bank_account=self.savings,
            amount=Decimal("250.00"),
            transfer_date=date(2026, 7, 1),
        )

        self.assertEqual(bank_account_balance(self.cash), Decimal("750.00"))
        self.assertEqual(bank_account_balance(self.savings), Decimal("250.00"))
        self.assertEqual(transfer.source_transaction.type, Transaction.EXPENSE)
        self.assertEqual(transfer.destination_transaction.type, Transaction.INCOME)
        self.assertEqual(transfer.source_transaction.amount, Decimal("250.00"))
        self.assertEqual(transfer.destination_transaction.amount, Decimal("250.00"))
        self.assertIsNone(transfer.source_transaction.category)
        self.assertIsNone(transfer.destination_transaction.category)


class CrossCurrencyTransferTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.cash = ensure_cash_bank_account(self.user)
        self.euro_account = create_bank_account(
            self.user,
            name="Revolut EUR",
            currency="EUR",
        )
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=self.cash,
        )

    @patch(
        "financetracker.services.bank_accounts.convert",
        return_value=Decimal("10.00"),
    )
    def test_cross_currency_transfer_credits_destination_in_its_currency(
        self, _mock_convert
    ):
        transfer = create_transfer(
            self.user,
            from_bank_account=self.cash,
            to_bank_account=self.euro_account,
            amount=Decimal("250.00"),
            transfer_date=date(2026, 7, 1),
        )

        self.assertEqual(bank_account_balance(self.cash), Decimal("750.00"))
        self.assertEqual(bank_account_balance(self.euro_account), Decimal("10.00"))
        self.assertEqual(transfer.source_transaction.currency, "CZK")
        self.assertEqual(transfer.destination_transaction.currency, "EUR")
        self.assertEqual(transfer.destination_transaction.amount, Decimal("10.00"))

    @patch(
        "financetracker.services.bank_accounts.convert",
        side_effect=CurrencyConversionError("no rate"),
    )
    def test_unavailable_rate_raises_bank_account_error(self, _mock_convert):
        with self.assertRaises(BankAccountError):
            create_transfer(
                self.user,
                from_bank_account=self.cash,
                to_bank_account=self.euro_account,
                amount=Decimal("250.00"),
                transfer_date=date(2026, 7, 1),
            )

        self.assertEqual(bank_account_balance(self.cash), Decimal("1000.00"))
        self.assertEqual(bank_account_balance(self.euro_account), Decimal("0"))


class TransferSpendingExclusionTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.cash = ensure_cash_bank_account(self.user)
        self.savings = create_bank_account(
            self.user,
            name="Savings",
            currency="CZK",
        )

    def test_transfer_legs_excluded_from_spending_statistics(self):
        ordinary = create_transaction(
            self.user,
            amount=Decimal("40.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            bank_account=self.cash,
        )
        create_transfer(
            self.user,
            from_bank_account=self.cash,
            to_bank_account=self.savings,
            amount=Decimal("100.00"),
            transfer_date=date(2026, 7, 1),
        )

        qs = exclude_from_spending_statistics(
            Transaction.objects.filter(user=self.user)
        )

        self.assertEqual(list(qs), [ordinary])
        self.assertEqual(bank_account_balance(self.cash), Decimal("-140.00"))
        self.assertEqual(bank_account_balance(self.savings), Decimal("100.00"))


class TransferUpdateDeleteTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.cash = ensure_cash_bank_account(self.user)
        self.savings = create_bank_account(
            self.user,
            name="Savings",
            currency="CZK",
        )
        self.checking = create_bank_account(
            self.user,
            name="Checking",
            currency="CZK",
        )
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=self.cash,
        )
        self.transfer = create_transfer(
            self.user,
            from_bank_account=self.cash,
            to_bank_account=self.savings,
            amount=Decimal("200.00"),
            transfer_date=date(2026, 7, 1),
        )

    def test_update_transfer_rewrites_legs_and_balances(self):
        updated = update_transfer(
            self.transfer,
            from_bank_account=self.cash,
            to_bank_account=self.checking,
            amount=Decimal("150.00"),
            transfer_date=date(2026, 7, 15),
        )

        self.assertEqual(bank_account_balance(self.cash), Decimal("850.00"))
        self.assertEqual(bank_account_balance(self.savings), Decimal("0"))
        self.assertEqual(bank_account_balance(self.checking), Decimal("150.00"))
        self.assertEqual(updated.source_transaction.amount, Decimal("150.00"))
        self.assertEqual(updated.destination_transaction.bank_account, self.checking)
        self.assertEqual(updated.source_transaction.date, date(2026, 7, 15))

    def test_delete_transfer_removes_legs_and_restores_balances(self):
        delete_transfer(self.transfer)

        self.assertFalse(Transfer.objects.filter(pk=self.transfer.pk).exists())
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 1)
        self.assertEqual(bank_account_balance(self.cash), Decimal("1000.00"))
        self.assertEqual(bank_account_balance(self.savings), Decimal("0"))
