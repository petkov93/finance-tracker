from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Iterator

from financetracker.services import currency as currency_module
from financetracker.services.rate_source import RateNotAvailableForDate, RateSource


class FakeRateSource:
    def __init__(
        self,
        *,
        rates_by_date: dict[date | None, dict[str, Decimal]] | None = None,
        currencies: dict[str, str] | None = None,
        unavailable_dates: frozenset[date] | None = None,
        bulk_error: BaseException | None = None,
        currencies_error: BaseException | None = None,
    ) -> None:
        self.rates_by_date = dict(rates_by_date or {})
        self.currencies = dict(currencies or {})
        self.unavailable_dates = unavailable_dates or frozenset()
        self.bulk_error = bulk_error
        self.currencies_error = currencies_error
        self.fetch_bulk_calls: list[date | None] = []
        self.fetch_currencies_calls = 0

    def fetch_bulk_rates(self, *, on_date: date | None = None) -> dict[str, Decimal]:
        self.fetch_bulk_calls.append(on_date)
        if self.bulk_error is not None:
            raise self.bulk_error
        if on_date is not None and on_date in self.unavailable_dates:
            raise RateNotAvailableForDate()
        if on_date in self.rates_by_date:
            return dict(self.rates_by_date[on_date])
        if None in self.rates_by_date:
            return dict(self.rates_by_date[None])
        raise RateNotAvailableForDate()

    def fetch_supported_currencies(self) -> dict[str, str]:
        self.fetch_currencies_calls += 1
        if self.currencies_error is not None:
            raise self.currencies_error
        return dict(self.currencies)


@contextmanager
def override_rate_source(source: RateSource) -> Iterator[RateSource]:
    previous = currency_module._rate_source
    currency_module._rate_source = source
    try:
        yield source
    finally:
        currency_module._rate_source = previous
