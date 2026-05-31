from datetime import date
from decimal import Decimal

from django.test import TestCase

from financetracker.models import InvestmentEntry, Transaction
from financetracker.tests.factories import create_category, create_investment, create_transaction, create_user


class ModelTests(TestCase):
    def test_category_str(self):
        category = create_category(name="Transport")
        self.assertEqual(str(category), "Transport")

    def test_transaction_str(self):
        user = create_user()
        transaction = create_transaction(
            user,
            amount=Decimal("99.50"),
            type=Transaction.INCOME,
            transaction_date=date(2025, 1, 10),
        )
        self.assertIn("Income", str(transaction))
        self.assertIn("99.50", str(transaction))

    def test_investment_entry_str(self):
        user = create_user()
        entry = create_investment(
            user,
            amount=Decimal("250.00"),
            type=InvestmentEntry.PROFIT,
            entry_date=date(2025, 2, 1),
        )
        self.assertIn("Profit", str(entry))
        self.assertIn("250.00", str(entry))

    def test_transaction_category_set_null_on_delete(self):
        user = create_user()
        category = create_category()
        transaction = create_transaction(user, category=category)
        category.delete()
        transaction.refresh_from_db()
        self.assertIsNone(transaction.category)

    def test_models_order_by_date_desc(self):
        user = create_user()
        older = create_transaction(user, transaction_date=date(2025, 1, 1))
        newer = create_transaction(user, transaction_date=date(2025, 2, 1))
        ordered = list(Transaction.objects.filter(user=user))
        self.assertEqual(ordered, [newer, older])
