from datetime import date
from decimal import Decimal

from django.test import TestCase

from financetracker.models import Transaction
from financetracker.services.display_conversion import (
    DisplayConversionResult,
    DisplayTransactionRow,
)
from financetracker.services.statistics_aggregation import aggregate_for_statistics
from financetracker.tests.factories import create_category, create_transaction, create_user


def _display(
    rows,
    *,
    default_currency="CZK",
    conversion_degraded=False,
):
    return DisplayConversionResult(
        rows=rows,
        total_income=None if conversion_degraded else Decimal("0"),
        total_expense=None if conversion_degraded else Decimal("0"),
        balance=None if conversion_degraded else Decimal("0"),
        conversion_degraded=conversion_degraded,
        rates_stale_date=None,
        default_currency=default_currency,
    )


def _row(
    transaction,
    *,
    primary_amount=None,
    primary_currency=None,
    show_native_footnote=False,
):
    amount = primary_amount if primary_amount is not None else transaction.amount
    currency = primary_currency if primary_currency is not None else transaction.currency
    return DisplayTransactionRow(
        transaction=transaction,
        primary_amount=amount,
        primary_currency=currency,
        native_amount=transaction.amount,
        native_currency=transaction.currency,
        show_native_footnote=show_native_footnote,
    )


class StatisticsAggregationTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_degraded_conversion_yields_empty_series(self):
        transaction = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type=Transaction.INCOME,
        )
        display = _display(
            [_row(transaction)],
            conversion_degraded=True,
        )

        result = aggregate_for_statistics(display)

        self.assertEqual(result.month_labels, [])
        self.assertEqual(result.monthly_income, [])
        self.assertEqual(result.monthly_expense, [])
        self.assertEqual(result.expense_category_labels, [])
        self.assertEqual(result.expense_category_values, [])
        self.assertEqual(result.income_category_labels, [])
        self.assertEqual(result.income_category_values, [])
        self.assertFalse(result.has_expense_categories)
        self.assertFalse(result.has_income_categories)

    def test_monthly_series_from_same_currency_rows(self):
        income = create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
            transaction_date=date(2025, 2, 5),
        )
        expense = create_transaction(
            self.user,
            amount=Decimal("400.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            transaction_date=date(2025, 2, 20),
        )
        display = _display(
            [
                _row(income, primary_currency="CZK"),
                _row(expense, primary_currency="CZK"),
            ]
        )

        result = aggregate_for_statistics(display)

        self.assertEqual(result.month_labels, ["Feb 2025"])
        self.assertEqual(result.monthly_income, [Decimal("1000.00")])
        self.assertEqual(result.monthly_expense, [Decimal("400.00")])

    def test_category_series_excludes_uncategorized_and_sorts_by_amount(self):
        food = create_category(name="Food")
        rent = create_category(name="Rent")
        salary = create_category(name="Salary", type=Transaction.INCOME)
        food_row = create_transaction(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            category=food,
            transaction_date=date(2025, 5, 1),
        )
        rent_row = create_transaction(
            self.user,
            amount=Decimal("800.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            category=rent,
            transaction_date=date(2025, 5, 2),
        )
        uncategorized = create_transaction(
            self.user,
            amount=Decimal("50.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            category=None,
            transaction_date=date(2025, 5, 3),
        )
        income = create_transaction(
            self.user,
            amount=Decimal("3000.00"),
            currency="CZK",
            type=Transaction.INCOME,
            category=salary,
            transaction_date=date(2025, 5, 4),
        )
        display = _display(
            [
                _row(food_row),
                _row(rent_row),
                _row(uncategorized),
                _row(income),
            ]
        )

        result = aggregate_for_statistics(display)

        self.assertEqual(result.expense_category_labels, ["Rent", "Food"])
        self.assertEqual(
            result.expense_category_values,
            [Decimal("800.00"), Decimal("100.00")],
        )
        self.assertEqual(result.income_category_labels, ["Salary"])
        self.assertEqual(result.income_category_values, [Decimal("3000.00")])
        self.assertTrue(result.has_expense_categories)
        self.assertTrue(result.has_income_categories)

    def test_skips_foreign_currency_rows_without_native_footnote(self):
        included = create_transaction(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            category=create_category(name="Food"),
            transaction_date=date(2025, 3, 1),
        )
        skipped = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type=Transaction.EXPENSE,
            category=create_category(name="Travel"),
            transaction_date=date(2025, 3, 2),
        )
        display = _display(
            [
                _row(included, primary_currency="CZK"),
                _row(
                    skipped,
                    primary_amount=Decimal("10.00"),
                    primary_currency="EUR",
                    show_native_footnote=False,
                ),
            ]
        )

        result = aggregate_for_statistics(display)

        self.assertEqual(result.month_labels, ["Mar 2025"])
        self.assertEqual(result.monthly_expense, [Decimal("100.00")])
        self.assertEqual(result.expense_category_labels, ["Food"])
        self.assertEqual(result.expense_category_values, [Decimal("100.00")])

    def test_includes_converted_rows_with_native_footnote(self):
        converted = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type=Transaction.INCOME,
            category=create_category(name="Salary", type=Transaction.INCOME),
            transaction_date=date(2025, 2, 5),
        )
        local = create_transaction(
            self.user,
            amount=Decimal("400.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            category=create_category(name="Food"),
            transaction_date=date(2025, 2, 20),
        )
        display = _display(
            [
                _row(
                    converted,
                    primary_amount=Decimal("250.00"),
                    primary_currency="CZK",
                    show_native_footnote=True,
                ),
                _row(local, primary_currency="CZK"),
            ]
        )

        result = aggregate_for_statistics(display)

        self.assertEqual(result.month_labels, ["Feb 2025"])
        self.assertEqual(result.monthly_income, [Decimal("250.00")])
        self.assertEqual(result.monthly_expense, [Decimal("400.00")])
        self.assertEqual(result.expense_category_labels, ["Food"])
        self.assertEqual(result.expense_category_values, [Decimal("400.00")])
        self.assertEqual(result.income_category_labels, ["Salary"])
        self.assertEqual(result.income_category_values, [Decimal("250.00")])

    def test_months_ordered_chronologically(self):
        jan = create_transaction(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
            type=Transaction.INCOME,
            transaction_date=date(2025, 1, 15),
        )
        mar = create_transaction(
            self.user,
            amount=Decimal("200.00"),
            currency="CZK",
            type=Transaction.INCOME,
            transaction_date=date(2025, 3, 15),
        )
        display = _display([_row(mar), _row(jan)])

        result = aggregate_for_statistics(display)

        self.assertEqual(result.month_labels, ["Jan 2025", "Mar 2025"])
        self.assertEqual(
            result.monthly_income,
            [Decimal("100.00"), Decimal("200.00")],
        )
