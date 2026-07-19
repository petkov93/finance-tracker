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
    is_iou_linked: bool = False

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
    iou_linked_ids: set[int],
) -> DisplayTransactionRow:
    is_iou_linked = transaction.pk in iou_linked_ids
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
            is_iou_linked=is_iou_linked,
        )

    if transaction.currency == default_currency:
        return DisplayTransactionRow(
            transaction=transaction,
            primary_amount=transaction.amount,
            primary_currency=default_currency,
            transaction_amount=transaction.amount,
            transaction_currency=transaction.currency,
            conversion_outcome=RowConversionOutcome.IN_DEFAULT_CURRENCY,
            is_iou_linked=is_iou_linked,
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
            is_iou_linked=is_iou_linked,
        )

    return DisplayTransactionRow(
        transaction=transaction,
        primary_amount=converted,
        primary_currency=default_currency,
        transaction_amount=transaction.amount,
        transaction_currency=transaction.currency,
        conversion_outcome=RowConversionOutcome.CONVERTED,
        is_iou_linked=is_iou_linked,
    )


def _sum_converted_totals(
    transactions: Iterable[Transaction],
    default_currency: str,
    rates: dict[tuple[str, str, date], Decimal],
) -> tuple[Decimal, Decimal]:
    total_income = Decimal("0")
    total_expense = Decimal("0")
    for transaction in transactions:
        converted = _converted_amount(transaction, default_currency, rates)
        if converted is None:
            continue
        if transaction.type == Transaction.INCOME:
            total_income += converted
        else:
            total_expense += converted
    return total_income, total_expense


def convert_for_display(
    transactions: Iterable[Transaction],
    default_currency: str,
    *,
    totals_transactions: Iterable[Transaction] | None = None,
    spending_totals_transactions: Iterable[Transaction] | None = None,
    iou_linked_transaction_ids: set[int] | None = None,
) -> DisplayConversionResult:
    list_transactions = list(transactions)
    totals_source = (
        list(totals_transactions)
        if totals_transactions is not None
        else list_transactions
    )
    spending_source = (
        list(spending_totals_transactions)
        if spending_totals_transactions is not None
        else totals_source
    )
    iou_linked_ids = iou_linked_transaction_ids or set()

    rate_keys = _collect_rate_keys(list_transactions, default_currency) | _collect_rate_keys(
        totals_source,
        default_currency,
    ) | _collect_rate_keys(spending_source, default_currency)
    rates, conversion_degraded, rates_stale_date = _fetch_rates(rate_keys)

    rows = [
        _build_row(
            transaction,
            default_currency,
            rates,
            degraded=conversion_degraded,
            iou_linked_ids=iou_linked_ids,
        )
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

    balance_income, balance_expense = _sum_converted_totals(
        totals_source,
        default_currency,
        rates,
    )
    total_income, total_expense = _sum_converted_totals(
        spending_source,
        default_currency,
        rates,
    )

    return DisplayConversionResult(
        rows=rows,
        total_income=total_income,
        total_expense=total_expense,
        balance=balance_income - balance_expense,
        conversion_degraded=False,
        rates_stale_date=rates_stale_date,
        default_currency=default_currency,
    )
