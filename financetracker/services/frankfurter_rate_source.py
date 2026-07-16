from datetime import date
from decimal import Decimal

import requests

from financetracker.services.rate_source import (
    CurrencyConversionError,
    RateNotAvailableForDate,
)

FRANKFURTER_API_BASE = "https://api.frankfurter.dev"
REQUEST_TIMEOUT_SECONDS = 3


def _parse_bulk_rates_response(data: object) -> dict[str, Decimal]:
    if not isinstance(data, list) or not data or "rate" not in data[0]:
        raise CurrencyConversionError("Missing rates in bulk response")

    return {item["quote"].upper(): Decimal(str(item["rate"])) for item in data}


class FrankfurterRateSource:
    def fetch_bulk_rates(self, *, on_date: date | None = None) -> dict[str, Decimal]:
        if on_date is None:
            url = f"{FRANKFURTER_API_BASE}/v2/rates"
        else:
            url = f"{FRANKFURTER_API_BASE}/v2/rates?date={on_date.isoformat()}"

        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise CurrencyConversionError("Failed to fetch bulk exchange rates") from exc

        if response.status_code == 404:
            raise RateNotAvailableForDate()

        try:
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise CurrencyConversionError("Failed to fetch bulk exchange rates") from exc
        except ValueError as exc:
            raise CurrencyConversionError("Invalid JSON in bulk rates response") from exc

        return _parse_bulk_rates_response(data)

    def fetch_supported_currencies(self) -> dict[str, str]:
        url = f"{FRANKFURTER_API_BASE}/v2/currencies"
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise CurrencyConversionError("Failed to fetch supported currencies") from exc
        except ValueError as exc:
            raise CurrencyConversionError("Invalid JSON in currencies response") from exc

        if not isinstance(data, list) or not data:
            raise CurrencyConversionError("Missing currencies in response")

        return {currency["iso_code"].upper(): currency["name"] for currency in data}
