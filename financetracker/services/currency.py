from decimal import Decimal

import requests
from django.core.cache import cache

FRANKFURTER_API_BASE = "https://api.frankfurter.dev"
REQUEST_TIMEOUT_SECONDS = 10
RATE_CACHE_TTL_SECONDS = 12 * 60 * 60
SUPPORTED_CURRENCIES_CACHE_KEY = "currency_supported_currencies"
SUPPORTED_CURRENCIES_CACHE_TTL_SECONDS = 24 * 60 * 60


class CurrencyConversionError(Exception):
    """Raised when a currency rate cannot be fetched or parsed."""


def _normalize_currency(code: str) -> str:
    return code.upper()


def _cache_key(from_currency: str, to_currency: str) -> str:
    return f"currency_rate_{from_currency}_{to_currency}"


def get_rate(from_currency: str, to_currency: str) -> Decimal:
    from_code = _normalize_currency(from_currency)
    to_code = _normalize_currency(to_currency)

    if from_code == to_code:
        return Decimal("1")

    cache_key = _cache_key(from_code, to_code)
    cached_rate = cache.get(cache_key)
    if cached_rate is not None:
        return Decimal(str(cached_rate))

    url = f"{FRANKFURTER_API_BASE}/v2/rate/{from_code}/{to_code}"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise CurrencyConversionError(
            f"Failed to fetch rate for {from_code}/{to_code}"
        ) from exc
    except ValueError as exc:
        raise CurrencyConversionError(
            f"Invalid JSON in rate response for {from_code}/{to_code}"
        ) from exc

    if not isinstance(data, dict) or "rate" not in data:
        raise CurrencyConversionError(
            f"Missing rate in response for {from_code}/{to_code}"
        )

    try:
        rate = Decimal(str(data["rate"]))
    except Exception as exc:
        raise CurrencyConversionError(
            f"Invalid rate value for {from_code}/{to_code}"
        ) from exc

    cache.set(cache_key, str(rate), RATE_CACHE_TTL_SECONDS)
    return rate


def convert(amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
    if amount <= 0:
        raise ValueError("amount must be positive")

    return amount * get_rate(from_currency, to_currency)


def get_supported_currencies() -> dict[str, str]:
    cached = cache.get(SUPPORTED_CURRENCIES_CACHE_KEY)
    if cached is not None:
        return dict(cached)

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

    currencies = {currency['iso_code'].upper(): currency['name'] for currency in data}

    cache.set(
        SUPPORTED_CURRENCIES_CACHE_KEY,
        currencies,
        SUPPORTED_CURRENCIES_CACHE_TTL_SECONDS
    )
    return currencies
