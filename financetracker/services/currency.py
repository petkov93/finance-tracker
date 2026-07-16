import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from django.db import OperationalError, transaction
from django.db.models import Count
from django.utils import timezone

from financetracker.models import EUR_BASE_CURRENCY, ExchangeRate, SyncMetadata
from financetracker.services.frankfurter_rate_source import FrankfurterRateSource
from financetracker.services.rate_source import CurrencyConversionError, RateNotAvailableForDate

MAX_RATE_WALKBACK_DAYS = 7

logger = logging.getLogger(__name__)

_rate_source = FrankfurterRateSource()


@dataclass(frozen=True)
class RateResult:
    rate: Decimal
    stale_date: date | None = None


def _normalize_currency(code: str) -> str:
    return code.upper()


def _expected_quote_count() -> int | None:
    """Number of EUR-quote rows a complete daily snapshot should contain."""
    currencies = SyncMetadata.get_singleton().supported_currencies
    if not currencies:
        return None
    return sum(
        1 for code in currencies if str(code).upper() != EUR_BASE_CURRENCY
    )


def _upsert_exchange_rates(rate_date: date, rates: dict[str, Decimal]) -> None:
    fetched_at = timezone.now()
    rows = [
        ExchangeRate(
            base_currency=EUR_BASE_CURRENCY,
            quote_currency=quote_currency,
            rate_date=rate_date,
            rate=rate,
            fetched_at=fetched_at,
        )
        for quote_currency, rate in rates.items()
    ]
    with transaction.atomic():
        ExchangeRate.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=["base_currency", "quote_currency", "rate_date"],
            update_fields=["rate", "fetched_at"],
        )


def _has_date_snapshot(rate_date: date) -> bool:
    actual = ExchangeRate.objects.filter(rate_date=rate_date).count()
    if actual == 0:
        return False
    expected = _expected_quote_count()
    if expected is None:
        return True
    return actual >= expected


def _ensure_date_snapshot(rate_date: date, *, force: bool = False) -> None:
    if not force and _has_date_snapshot(rate_date):
        return

    for days_back in range(MAX_RATE_WALKBACK_DAYS + 1):
        lookup_date = rate_date - timedelta(days=days_back)
        try:
            rates = _rate_source.fetch_bulk_rates(on_date=lookup_date)
        except RateNotAvailableForDate:
            continue

        _upsert_exchange_rates(rate_date, rates)
        return

    raise CurrencyConversionError(
        f"No published bulk rates found near {rate_date.isoformat()}"
    )


def ensure_rate_snapshots(dates: Iterable[date]) -> None:
    today = date.today()
    pending = sorted({rate_date for rate_date in dates if rate_date < today})
    if not pending:
        return

    expected = _expected_quote_count()
    counts = {
        row["rate_date"]: row["c"]
        for row in (
            ExchangeRate.objects.filter(rate_date__in=pending)
            .values("rate_date")
            .annotate(c=Count("id"))
        )
    }
    for rate_date in pending:
        actual = counts.get(rate_date, 0)
        complete = actual > 0 and (expected is None or actual >= expected)
        if complete:
            continue
        try:
            _ensure_date_snapshot(rate_date, force=actual > 0)
        except CurrencyConversionError:
            continue


def _is_sync_stale(metadata: SyncMetadata | None = None) -> bool:
    if metadata is None:
        metadata = SyncMetadata.get_singleton()
    return (
        metadata.last_successful_sync_date is None
        or metadata.last_successful_sync_date < date.today()
    )


def _try_acquire_sync_lock() -> bool:
    try:
        SyncMetadata.get_singleton()
        with transaction.atomic():
            metadata = SyncMetadata.objects.select_for_update().get(pk=1)
            if metadata.sync_in_progress or not _is_sync_stale(metadata):
                return False
            metadata.sync_in_progress = True
            metadata.save(update_fields=["sync_in_progress"])
            return True
    except OperationalError:
        # SQLite can raise "database is locked" under concurrent writers.
        return False


def _release_sync_lock() -> None:
    try:
        SyncMetadata.objects.filter(pk=1).update(sync_in_progress=False)
    except OperationalError:
        logger.warning("Failed to release exchange-rate sync lock")


def ensure_sync_if_stale() -> None:
    if not _try_acquire_sync_lock():
        return
    try:
        sync_latest_rates()
    except CurrencyConversionError as exc:
        logger.warning("Exchange rate sync failed: %s", exc)
    finally:
        _release_sync_lock()


def sync_latest_rates() -> None:
    today = date.today()
    rates = _rate_source.fetch_bulk_rates()
    currencies = _rate_source.fetch_supported_currencies()

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


def _most_recent_rate_date_for_quote(quote_currency: str) -> date | None:
    row = (
        ExchangeRate.objects.filter(
            base_currency=EUR_BASE_CURRENCY,
            quote_currency=quote_currency,
        )
        .order_by("-rate_date")
        .first()
    )
    return row.rate_date if row else None


def _get_eur_quote_rate_with_fallback(
    quote_currency: str,
    rate_date: date,
) -> tuple[Decimal, date | None]:
    if quote_currency == EUR_BASE_CURRENCY:
        return Decimal("1"), None

    try:
        return _get_eur_quote_rate(quote_currency, rate_date), None
    except CurrencyConversionError:
        recent_date = _most_recent_rate_date_for_quote(quote_currency)
        if recent_date is None:
            raise
        return _get_eur_quote_rate(quote_currency, recent_date), recent_date


def _derive_rate_from_eur_snapshot(
    from_code: str,
    to_code: str,
    rate_date: date,
) -> Decimal:
    eur_to_from = _get_eur_quote_rate(from_code, rate_date)
    eur_to_to = _get_eur_quote_rate(to_code, rate_date)
    return eur_to_to / eur_to_from


def _derive_rate_with_stale_fallback(
    from_code: str,
    to_code: str,
    rate_date: date,
) -> RateResult:
    try:
        rate = _derive_rate_from_eur_snapshot(from_code, to_code, rate_date)
        return RateResult(rate=rate, stale_date=None)
    except CurrencyConversionError:
        eur_to_from, stale_from = _get_eur_quote_rate_with_fallback(from_code, rate_date)
        eur_to_to, stale_to = _get_eur_quote_rate_with_fallback(to_code, rate_date)
        stale_dates = [d for d in (stale_from, stale_to) if d is not None]
        stale_date = max(stale_dates) if stale_dates else None
        return RateResult(rate=eur_to_to / eur_to_from, stale_date=stale_date)


def _get_latest_rate(from_code: str, to_code: str) -> RateResult:
    ensure_sync_if_stale()
    today = date.today()

    if not _has_date_snapshot(today):
        try:
            _ensure_date_snapshot(today)
        except CurrencyConversionError:
            pass

    return _derive_rate_with_stale_fallback(from_code, to_code, today)


def _get_historical_rate(from_code: str, to_code: str, on_date: date) -> RateResult:
    _ensure_date_snapshot(on_date)
    try:
        rate = _derive_rate_from_eur_snapshot(from_code, to_code, on_date)
    except CurrencyConversionError:
        # Partial snapshot (e.g. interrupted upsert) with no size baseline.
        _ensure_date_snapshot(on_date, force=True)
        rate = _derive_rate_from_eur_snapshot(from_code, to_code, on_date)
    return RateResult(rate=rate, stale_date=None)


def get_rate(
    from_currency: str,
    to_currency: str,
    *,
    on_date: date | None = None,
) -> RateResult:
    from_code = _normalize_currency(from_currency)
    to_code = _normalize_currency(to_currency)

    if from_code == to_code:
        return RateResult(rate=Decimal("1"), stale_date=None)

    if on_date is not None and on_date < date.today():
        return _get_historical_rate(from_code, to_code, on_date)

    return _get_latest_rate(from_code, to_code)


def _derive_rate_from_eur_map(
    eur_rates: dict[tuple[str, date], Decimal],
    from_code: str,
    to_code: str,
    rate_date: date,
) -> Decimal:
    if from_code == EUR_BASE_CURRENCY:
        eur_to_from = Decimal("1")
    else:
        try:
            eur_to_from = eur_rates[(from_code, rate_date)]
        except KeyError as exc:
            raise CurrencyConversionError(
                f"No stored rate for {EUR_BASE_CURRENCY}/{from_code} "
                f"on {rate_date.isoformat()}"
            ) from exc

    if to_code == EUR_BASE_CURRENCY:
        eur_to_to = Decimal("1")
    else:
        try:
            eur_to_to = eur_rates[(to_code, rate_date)]
        except KeyError as exc:
            raise CurrencyConversionError(
                f"No stored rate for {EUR_BASE_CURRENCY}/{to_code} "
                f"on {rate_date.isoformat()}"
            ) from exc

    return eur_to_to / eur_to_from


def get_rates(
    keys: Iterable[tuple[str, str, date]],
) -> dict[tuple[str, str, date], RateResult]:
    """Resolve many (from, to, on_date) keys with bulk historical DB reads."""
    today = date.today()
    normalized: list[tuple[str, str, date]] = []
    for from_currency, to_currency, on_date in keys:
        normalized.append(
            (
                _normalize_currency(from_currency),
                _normalize_currency(to_currency),
                on_date,
            )
        )

    historical = [
        (f, t, d) for f, t, d in normalized if f != t and d < today
    ]
    latest = [(f, t, d) for f, t, d in normalized if f != t and d >= today]
    identity = [(f, t, d) for f, t, d in normalized if f == t]

    results: dict[tuple[str, str, date], RateResult] = {
        (f, t, d): RateResult(rate=Decimal("1"), stale_date=None)
        for f, t, d in identity
    }

    if historical:
        try:
            ensure_rate_snapshots({d for _, _, d in historical})
        except CurrencyConversionError:
            pass
        dates = {d for _, _, d in historical}
        quotes = {
            code
            for f, t, _ in historical
            for code in (f, t)
            if code != EUR_BASE_CURRENCY
        }
        eur_rates = {
            (quote, rate_date): rate
            for quote, rate_date, rate in ExchangeRate.objects.filter(
                base_currency=EUR_BASE_CURRENCY,
                rate_date__in=dates,
                quote_currency__in=quotes,
            ).values_list("quote_currency", "rate_date", "rate")
        }
        missing_dates: set[date] = set()
        for from_code, to_code, on_date in historical:
            try:
                rate = _derive_rate_from_eur_map(
                    eur_rates, from_code, to_code, on_date
                )
            except CurrencyConversionError:
                missing_dates.add(on_date)
                continue
            results[(from_code, to_code, on_date)] = RateResult(
                rate=rate, stale_date=None
            )

        if missing_dates:
            for on_date in missing_dates:
                try:
                    _ensure_date_snapshot(on_date, force=True)
                except CurrencyConversionError:
                    continue
            eur_rates = {
                (quote, rate_date): rate
                for quote, rate_date, rate in ExchangeRate.objects.filter(
                    base_currency=EUR_BASE_CURRENCY,
                    rate_date__in=dates,
                    quote_currency__in=quotes,
                ).values_list("quote_currency", "rate_date", "rate")
            }
            for from_code, to_code, on_date in historical:
                if (from_code, to_code, on_date) in results:
                    continue
                try:
                    rate = _derive_rate_from_eur_map(
                        eur_rates, from_code, to_code, on_date
                    )
                except CurrencyConversionError:
                    continue
                results[(from_code, to_code, on_date)] = RateResult(
                    rate=rate, stale_date=None
                )

    for from_code, to_code, on_date in latest:
        try:
            results[(from_code, to_code, on_date)] = _get_latest_rate(
                from_code, to_code
            )
        except CurrencyConversionError:
            continue

    return results


def convert(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    *,
    on_date: date | None = None,
) -> Decimal:
    if amount <= 0:
        raise ValueError("amount must be positive")

    return amount * get_rate(from_currency, to_currency, on_date=on_date).rate


def get_supported_currencies() -> dict[str, str]:
    metadata = SyncMetadata.get_singleton()
    if metadata.supported_currencies:
        return dict(metadata.supported_currencies)

    return _rate_source.fetch_supported_currencies()
