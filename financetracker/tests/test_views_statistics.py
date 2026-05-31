import json
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import InvestmentEntry, Transaction
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_category,
    create_investment,
    create_transaction,
    create_user,
)


class StatisticsViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.category = create_category(name="Salary", type=Transaction.INCOME)
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)

    def test_statistics_default_date_range(self):
        response = self.client.get(reverse("statistics"))
        self.assertEqual(response.status_code, 200)
        today = date.today()
        self.assertEqual(response.context["from_date"], date(today.year, 1, 1).isoformat())
        self.assertEqual(response.context["to_date"], today.isoformat())

    def test_statistics_invalid_dates_fall_back_to_defaults(self):
        response = self.client.get(
            reverse("statistics"),
            {"from_date": "not-a-date", "to_date": "also-bad"},
        )
        today = date.today()
        self.assertEqual(response.context["from_date"], date(today.year, 1, 1).isoformat())
        self.assertEqual(response.context["to_date"], today.isoformat())

    def test_statistics_swaps_reversed_date_range(self):
        response = self.client.get(
            reverse("statistics"),
            {"from_date": "2025-06-01", "to_date": "2025-01-01"},
        )
        self.assertEqual(response.context["from_date"], "2025-01-01")
        self.assertEqual(response.context["to_date"], "2025-06-01")

    def test_statistics_totals_and_counts(self):
        create_transaction(
            self.user,
            amount=Decimal("3000.00"),
            type=Transaction.INCOME,
            category=self.category,
            transaction_date=date(2025, 3, 10),
        )
        create_transaction(
            self.user,
            amount=Decimal("500.00"),
            type=Transaction.EXPENSE,
            category=create_category(name="Food"),
            transaction_date=date(2025, 3, 15),
        )
        create_transaction(
            self.user,
            amount=Decimal("200.00"),
            type=Transaction.EXPENSE,
            transaction_date=date(2024, 12, 31),
        )

        response = self.client.get(
            reverse("statistics"),
            {"from_date": "2025-01-01", "to_date": "2025-12-31"},
        )
        self.assertEqual(response.context["total_income"], 3000.0)
        self.assertEqual(response.context["total_expense"], 500.0)
        self.assertEqual(response.context["balance"], 2500.0)
        self.assertEqual(response.context["total_count"], 2)
        self.assertEqual(response.context["income_count"], 1)
        self.assertEqual(response.context["expense_count"], 1)

    def test_statistics_monthly_aggregation(self):
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            type=Transaction.INCOME,
            transaction_date=date(2025, 2, 5),
        )
        create_transaction(
            self.user,
            amount=Decimal("400.00"),
            type=Transaction.EXPENSE,
            transaction_date=date(2025, 2, 20),
        )

        response = self.client.get(
            reverse("statistics"),
            {"from_date": "2025-02-01", "to_date": "2025-02-28"},
        )
        month_labels = json.loads(response.context["month_labels"])
        monthly_income = json.loads(response.context["monthly_income"])
        monthly_expense = json.loads(response.context["monthly_expense"])

        self.assertEqual(month_labels, ["Feb 2025"])
        self.assertEqual(monthly_income, [1000.0])
        self.assertEqual(monthly_expense, [400.0])

    def test_statistics_category_breakdown_excludes_null_categories(self):
        create_transaction(
            self.user,
            amount=Decimal("100.00"),
            type=Transaction.EXPENSE,
            category=create_category(name="Food"),
            transaction_date=date(2025, 5, 1),
        )
        create_transaction(
            self.user,
            amount=Decimal("50.00"),
            type=Transaction.EXPENSE,
            category=None,
            transaction_date=date(2025, 5, 2),
        )

        response = self.client.get(
            reverse("statistics"),
            {"from_date": "2025-05-01", "to_date": "2025-05-31"},
        )
        cat_labels = json.loads(response.context["cat_labels"])
        cat_values = json.loads(response.context["cat_values"])
        self.assertEqual(cat_labels, ["Food"])
        self.assertEqual(cat_values, [100.0])
        self.assertTrue(response.context["has_expense_categories"])
