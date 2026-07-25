import importlib

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase

from financetracker.models import BankAccount, UserProfile

backfill_cash_bank_accounts = importlib.import_module(
    "financetracker.migrations.0012_bank_account_and_transaction_fk"
).backfill_cash_bank_accounts


class BankAccountMigrationTests(TestCase):
    def test_backfill_creates_cash_with_profile_currency(self):
        user = User.objects.create_user(username="legacy", password="pass1234")
        UserProfile.objects.create(user=user, default_currency="EUR")
        self.assertFalse(BankAccount.objects.filter(user=user).exists())

        backfill_cash_bank_accounts(apps, None)

        cash = BankAccount.objects.get(user=user, is_cash=True)
        self.assertEqual(cash.name, "Cash")
        self.assertEqual(cash.currency, "EUR")

    def test_backfill_uses_czk_when_profile_missing(self):
        user = User.objects.create_user(username="noprofile", password="pass1234")
        UserProfile.objects.filter(user=user).delete()
        self.assertFalse(BankAccount.objects.filter(user=user).exists())

        backfill_cash_bank_accounts(apps, None)

        cash = BankAccount.objects.get(user=user, is_cash=True)
        self.assertEqual(cash.currency, "CZK")
