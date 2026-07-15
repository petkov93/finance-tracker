from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financetracker.models import Transaction
from financetracker.services.display_conversion import (
    DisplayConversionResult,
    DisplayTransactionRow,
)


@dataclass(frozen=True)
class StatisticsAggregationResult:
    month_labels: list[str]
    monthly_income: list[Decimal]
    monthly_expense: list[Decimal]
    expense_category_labels: list[str]
    expense_category_values: list[Decimal]
    income_category_labels: list[str]
    income_category_values: list[Decimal]
    has_expense_categories: bool
    has_income_categories: bool


def _empty_result() -> StatisticsAggregationResult:
    return StatisticsAggregationResult(
        month_labels=[],
        monthly_income=[],
        monthly_expense=[],
        expense_category_labels=[],
        expense_category_values=[],
        income_category_labels=[],
        income_category_values=[],
        has_expense_categories=False,
        has_income_categories=False,
    )


def _row_contributes_to_statistics(
    row: DisplayTransactionRow,
    default_currency: str,
) -> bool:
    transaction = row.transaction
    return (
        transaction.currency == default_currency
        or row.show_native_footnote
    )


def _sorted_category_series(
    amounts_by_category: dict[str, Decimal],
) -> tuple[list[str], list[Decimal]]:
    labels = sorted(
        amounts_by_category.keys(),
        key=lambda name: amounts_by_category[name],
        reverse=True,
    )
    values = [amounts_by_category[name] for name in labels]
    return labels, values


def aggregate_for_statistics(
    display: DisplayConversionResult,
) -> StatisticsAggregationResult:
    if display.conversion_degraded:
        return _empty_result()

    months_map: dict[str, dict[str, Decimal]] = {}
    month_order: dict[str, date] = {}
    expense_by_category: dict[str, Decimal] = {}
    income_by_category: dict[str, Decimal] = {}

    for row in display.rows:
        if not _row_contributes_to_statistics(row, display.default_currency):
            continue

        transaction = row.transaction
        amount = row.primary_amount
        month_start = transaction.date.replace(day=1)
        month_label = month_start.strftime("%b %Y")
        if month_label not in months_map:
            months_map[month_label] = {
                "income": Decimal("0"),
                "expense": Decimal("0"),
            }
            month_order[month_label] = month_start
        months_map[month_label][transaction.type] += amount

        if transaction.category is None:
            continue
        category_name = transaction.category.name
        if transaction.type == Transaction.EXPENSE:
            expense_by_category[category_name] = (
                expense_by_category.get(category_name, Decimal("0")) + amount
            )
        else:
            income_by_category[category_name] = (
                income_by_category.get(category_name, Decimal("0")) + amount
            )

    month_labels = sorted(months_map.keys(), key=lambda label: month_order[label])
    monthly_income = [months_map[label]["income"] for label in month_labels]
    monthly_expense = [months_map[label]["expense"] for label in month_labels]

    expense_category_labels, expense_category_values = _sorted_category_series(
        expense_by_category
    )
    income_category_labels, income_category_values = _sorted_category_series(
        income_by_category
    )

    return StatisticsAggregationResult(
        month_labels=month_labels,
        monthly_income=monthly_income,
        monthly_expense=monthly_expense,
        expense_category_labels=expense_category_labels,
        expense_category_values=expense_category_values,
        income_category_labels=income_category_labels,
        income_category_values=income_category_values,
        has_expense_categories=bool(expense_category_labels),
        has_income_categories=bool(income_category_labels),
    )
