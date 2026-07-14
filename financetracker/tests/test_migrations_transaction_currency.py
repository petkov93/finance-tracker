import importlib

from django.apps import apps
from django.test import TestCase

from financetracker.models import Transaction
from financetracker.tests.factories import create_transaction, create_user

backfill_transaction_currencies = importlib.import_module(
    "financetracker.migrations.0005_transaction_currency"
).backfill_transaction_currencies


class TransactionCurrencyMigrationTests(TestCase):
    def test_backfill_sets_czk_for_existing_transactions(self):
        user = create_user()
        transaction = create_transaction(user)
        Transaction.objects.filter(pk=transaction.pk).update(currency="")

        backfill_transaction_currencies(apps, None)

        transaction.refresh_from_db()
        self.assertEqual(transaction.currency, "CZK")
