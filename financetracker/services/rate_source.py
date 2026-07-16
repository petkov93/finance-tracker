from datetime import date
from decimal import Decimal
from typing import Protocol


class CurrencyConversionError(Exception):
    """Raised when a currency rate cannot be fetched or parsed."""


class RateNotAvailableForDate(Exception):
    """Raised when the rate source has no published bulk snapshot for a date."""


class RateSource(Protocol):
    def fetch_bulk_rates(self, *, on_date: date | None = None) -> dict[str, Decimal]: ...

    def fetch_supported_currencies(self) -> dict[str, str]: ...
