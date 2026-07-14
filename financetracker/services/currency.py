from datetime import date, timedelta
from decimal import Decimal

import requests
from django.core.cache import cache
from django.utils import timezone

from financetracker.models import EUR_BASE_CURRENCY, ExchangeRate, SyncMetadata

FRANKFURTER_API_BASE = "https://api.frankfurter.dev"
REQUEST_TIMEOUT_SECONDS = 3
PAST_RATE_CACHE_TTL_SECONDS = 10 * 365 * 24 * 60 * 60
MAX_RATE_WALKBACK_DAYS = 7


class CurrencyConversionError(Exception):
    """Raised when a currency rate cannot be fetched or parsed."""


class _RateNotAvailableForDate(Exception):
    """Raised when Frankfurter has no published rate for a specific date."""


def _normalize_currency(code: str) -> str:
    return code.upper()


def _cache_key(from_currency: str, to_currency: str, on_date: date) -> str:
    return f"currency_rate_{from_currency}_{to_currency}_{on_date.isoformat()}"


def _parse_rate_response(data: object, from_code: str, to_code: str) -> Decimal:
    if not isinstance(data, dict) or "rate" not in data:
        raise CurrencyConversionError(
            f"Missing rate in response for {from_code}/{to_code}"
        )

    try:
        return Decimal(str(data["rate"]))
    except Exception as exc:
        raise CurrencyConversionError(
            f"Invalid rate value for {from_code}/{to_code}"
        ) from exc


def _fetch_rate(from_code: str, to_code: str, lookup_date: date | None) -> Decimal:
    if lookup_date is None:
        url = f"{FRANKFURTER_API_BASE}/v2/rate/{from_code}/{to_code}"
    else:
        url = (
            f"{FRANKFURTER_API_BASE}/v2/rate/{from_code}/{to_code}/"
            f"{lookup_date.isoformat()}"
        )

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise CurrencyConversionError(
            f"Failed to fetch rate for {from_code}/{to_code}"
        ) from exc

    if response.status_code == 404:
        raise _RateNotAvailableForDate()

    try:
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

    return _parse_rate_response(data, from_code, to_code)


def _fetch_bulk_rates() -> dict[str, Decimal]:
    url = f"{FRANKFURTER_API_BASE}/v2/rates"

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise CurrencyConversionError("Failed to fetch bulk exchange rates") from exc
    except ValueError as exc:
        raise CurrencyConversionError("Invalid JSON in bulk rates response") from exc

    if not isinstance(data, list) or 'rate' not in data[0]:
        raise CurrencyConversionError("Missing rates in bulk response")

    return {item['quote'].upper(): Decimal(str(item['rate'])) for item in data}


def _fetch_supported_currencies_from_api() -> dict[str, str]:
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


def _upsert_exchange_rates(rate_date: date, rates: dict[str, Decimal]) -> None:
    fetched_at = timezone.now()
    for quote_currency, rate in rates.items():
        ExchangeRate.objects.update_or_create(
            base_currency=EUR_BASE_CURRENCY,
            quote_currency=quote_currency,
            rate_date=rate_date,
            defaults={"rate": rate, "fetched_at": fetched_at},
        )


def sync_latest_rates() -> None:
    today = date.today()
    rates = _fetch_bulk_rates()
    currencies = _fetch_supported_currencies_from_api()

    _upsert_exchange_rates(today, rates)

    metadata = SyncMetadata.get_singleton()
    metadata.last_successful_sync_date = today
    metadata.supported_currencies = currencies
    metadata.save()


def _get_eur_quote_rate(quote_currency: str, rate_date: date) -> Decimal:
    if quote_currency == EUR_BASE_CURRENCY:
        return Decimal("1")

    try:
        row = ExchangeRate.objects.get(
            base_currency=EUR_BASE_CURRENCY,
            quote_currency=quote_currency,
            rate_date=rate_date,
        )
    except ExchangeRate.DoesNotExist as exc:
        raise CurrencyConversionError(
            f"No stored rate for {EUR_BASE_CURRENCY}/{quote_currency} on {rate_date.isoformat()}"
        ) from exc

    return row.rate


def _derive_rate_from_eur_snapshot(
    from_code: str,
    to_code: str,
    rate_date: date,
) -> Decimal:
    eur_to_from = _get_eur_quote_rate(from_code, rate_date)
    eur_to_to = _get_eur_quote_rate(to_code, rate_date)
    return eur_to_to / eur_to_from


def _get_latest_rate(from_code: str, to_code: str) -> Decimal:
    return _derive_rate_from_eur_snapshot(from_code, to_code, date.today())


def _get_historical_rate(from_code: str, to_code: str, on_date: date) -> Decimal:
    cache_key = _cache_key(from_code, to_code, on_date)
    cached_rate = cache.get(cache_key)
    if cached_rate is not None:
        return Decimal(str(cached_rate))

    for days_back in range(MAX_RATE_WALKBACK_DAYS + 1):
        lookup_date = on_date - timedelta(days=days_back)
        try:
            rate = _fetch_rate(from_code, to_code, lookup_date)
        except _RateNotAvailableForDate:
            continue

        cache.set(cache_key, str(rate), PAST_RATE_CACHE_TTL_SECONDS)
        return rate

    raise CurrencyConversionError(
        f"No published rate found for {from_code}/{to_code} near {on_date.isoformat()}"
    )


def get_rate(
    from_currency: str,
    to_currency: str,
    *,
    on_date: date | None = None,
) -> Decimal:
    from_code = _normalize_currency(from_currency)
    to_code = _normalize_currency(to_currency)

    if from_code == to_code:
        return Decimal("1")

    if on_date is not None and on_date < date.today():
        return _get_historical_rate(from_code, to_code, on_date)

    return _get_latest_rate(from_code, to_code)


def convert(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    *,
    on_date: date | None = None,
) -> Decimal:
    if amount <= 0:
        raise ValueError("amount must be positive")

    return amount * get_rate(from_currency, to_currency, on_date=on_date)


def get_supported_currencies() -> dict[str, str]:
    metadata = SyncMetadata.get_singleton()
    if metadata.supported_currencies:
        return dict(metadata.supported_currencies)

    return _fetch_supported_currencies_from_api()
