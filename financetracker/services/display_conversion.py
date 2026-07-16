from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Iterable

from financetracker.models import Transaction
from financetracker.services.currency import get_rates


class RowConversionOutcome(Enum):
    IN_DEFAULT_CURRENCY = "in_default_currency"
    CONVERTED = "converted"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class DisplayTransactionRow:
    transaction: Transaction
    primary_amount: Decimal
    primary_currency: str
    transaction_amount: Decimal
    transaction_currency: str
    conversion_outcome: RowConversionOutcome

    @property
    def show_transaction_currency_footnote(self) -> bool:
        return self.conversion_outcome == RowConversionOutcome.CONVERTED


@dataclass(frozen=True)
class DisplayConversionResult:
    rows: list[DisplayTransactionRow]
    total_income: Decimal | None
    total_expense: Decimal | None
    balance: Decimal | None
    conversion_degraded: bool
    rates_stale_date: date | None
    default_currency: str


def _requires_today_rate(on_date: date) -> bool:
    return on_date >= date.today()


def _collect_rate_keys(
    transactions: Iterable[Transaction],
    default_currency: str,
) -> set[tuple[str, str, date]]:
    keys: set[tuple[str, str, date]] = set()
    for transaction in transactions:
        if transaction.currency == default_currency:
            continue
        keys.add((transaction.currency, default_currency, transaction.date))
    return keys


def _fetch_rates(
    keys: set[tuple[str, str, date]],
) -> tuple[dict[tuple[str, str, date], Decimal], bool, date | None]:
    resolved = get_rates(keys)

    rates: dict[tuple[str, str, date], Decimal] = {}
    conversion_degraded = False
    rates_stale_date: date | None = None

    for from_currency, to_currency, on_date in keys:
        result = resolved.get((from_currency, to_currency, on_date))
        if result is None:
            if _requires_today_rate(on_date):
                conversion_degraded = True
            continue

        rates[(from_currency, to_currency, on_date)] = result.rate
        if result.stale_date is not None and _requires_today_rate(on_date):
            rates_stale_date = (
                max(rates_stale_date, result.stale_date)
                if rates_stale_date is not None
                else result.stale_date
            )

    return rates, conversion_degraded, rates_stale_date


def _converted_amount(
    transaction: Transaction,
    default_currency: str,
    rates: dict[tuple[str, str, date], Decimal],
) -> Decimal | None:
    if transaction.currency == default_currency:
        return transaction.amount

    rate = rates.get((transaction.currency, default_currency, transaction.date))
    if rate is None:
        return None

    return transaction.amount * rate


def _build_row(
    transaction: Transaction,
    default_currency: str,
    rates: dict[tuple[str, str, date], Decimal],
    *,
    degraded: bool,
) -> DisplayTransactionRow:
    if degraded:
        outcome = (
            RowConversionOutcome.IN_DEFAULT_CURRENCY
            if transaction.currency == default_currency
            else RowConversionOutcome.EXCLUDED
        )
        return DisplayTransactionRow(
            transaction=transaction,
            primary_amount=transaction.amount,
            primary_currency=transaction.currency,
            transaction_amount=transaction.amount,
            transaction_currency=transaction.currency,
            conversion_outcome=outcome,
        )

    if transaction.currency == default_currency:
        return DisplayTransactionRow(
            transaction=transaction,
            primary_amount=transaction.amount,
            primary_currency=default_currency,
            transaction_amount=transaction.amount,
            transaction_currency=transaction.currency,
            conversion_outcome=RowConversionOutcome.IN_DEFAULT_CURRENCY,
        )

    converted = _converted_amount(transaction, default_currency, rates)
    if converted is None:
        return DisplayTransactionRow(
            transaction=transaction,
            primary_amount=transaction.amount,
            primary_currency=transaction.currency,
            transaction_amount=transaction.amount,
            transaction_currency=transaction.currency,
            conversion_outcome=RowConversionOutcome.EXCLUDED,
        )

    return DisplayTransactionRow(
        transaction=transaction,
        primary_amount=converted,
        primary_currency=default_currency,
        transaction_amount=transaction.amount,
        transaction_currency=transaction.currency,
        conversion_outcome=RowConversionOutcome.CONVERTED,
    )


def convert_for_display(
    transactions: Iterable[Transaction],
    default_currency: str,
    *,
    totals_transactions: Iterable[Transaction] | None = None,
) -> DisplayConversionResult:
    list_transactions = list(transactions)
    totals_source = (
        list(totals_transactions)
        if totals_transactions is not None
        else list_transactions
    )

    rate_keys = _collect_rate_keys(list_transactions, default_currency) | _collect_rate_keys(
        totals_source,
        default_currency,
    )
    rates, conversion_degraded, rates_stale_date = _fetch_rates(rate_keys)

    rows = [
        _build_row(transaction, default_currency, rates, degraded=conversion_degraded)
        for transaction in list_transactions
    ]

    if conversion_degraded:
        return DisplayConversionResult(
            rows=rows,
            total_income=None,
            total_expense=None,
            balance=None,
            conversion_degraded=True,
            rates_stale_date=None,
            default_currency=default_currency,
        )

    total_income = Decimal("0")
    total_expense = Decimal("0")
    for transaction in totals_source:
        converted = _converted_amount(transaction, default_currency, rates)
        if converted is None:
            continue
        if transaction.type == Transaction.INCOME:
            total_income += converted
        else:
            total_expense += converted

    return DisplayConversionResult(
        rows=rows,
        total_income=total_income,
        total_expense=total_expense,
        balance=total_income - total_expense,
        conversion_degraded=False,
        rates_stale_date=rates_stale_date,
        default_currency=default_currency,
    )
