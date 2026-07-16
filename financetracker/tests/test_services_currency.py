from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from financetracker.models import ExchangeRate, SyncMetadata
from financetracker.services.currency import (
    CurrencyConversionError,
    RateResult,
    convert,
    ensure_rate_snapshots,
    ensure_sync_if_stale,
    get_rate,
    get_supported_currencies,
    sync_latest_rates,
)
from financetracker.tests.rate_source_support import FakeRateSource, override_rate_source


class CurrencyServiceTests(TestCase):
    def _seed_today_rates(self, rates: dict[str, Decimal]) -> None:
        fetched_at = timezone.now()
        for quote_currency, rate in rates.items():
            ExchangeRate.objects.create(
                base_currency="EUR",
                quote_currency=quote_currency,
                rate_date=date.today(),
                rate=rate,
                fetched_at=fetched_at,
            )
        metadata = SyncMetadata.get_singleton()
        metadata.last_successful_sync_date = date.today()
        metadata.save(update_fields=["last_successful_sync_date"])

    def test_sync_latest_rates_upserts_eur_base_rows_for_today(self):
        fake = FakeRateSource(
            rates_by_date={
                None: {"USD": Decimal("1.1"), "CZK": Decimal("25.0")},
            },
            currencies={
                "EUR": "Euro",
                "USD": "US Dollar",
                "CZK": "Czech Koruna",
            },
        )
        with override_rate_source(fake):
            sync_latest_rates()

        self.assertEqual(ExchangeRate.objects.filter(rate_date=date.today()).count(), 2)
        usd_row = ExchangeRate.objects.get(quote_currency="USD", rate_date=date.today())
        self.assertEqual(usd_row.base_currency, "EUR")
        self.assertEqual(usd_row.rate, Decimal("1.1"))

        metadata = SyncMetadata.get_singleton()
        self.assertEqual(metadata.last_successful_sync_date, date.today())
        self.assertEqual(
            metadata.supported_currencies,
            {
                "EUR": "Euro",
                "USD": "US Dollar",
                "CZK": "Czech Koruna",
            },
        )

    def test_cross_derivation_from_stored_eur_rates(self):
        self._seed_today_rates({"USD": Decimal("1.1"), "CZK": Decimal("25.0")})

        with override_rate_source(FakeRateSource()):
            result = get_rate("USD", "CZK")

        self.assertEqual(result.rate, Decimal("25.0") / Decimal("1.1"))
        self.assertIsNone(result.stale_date)

    def test_same_currency_conversion_returns_amount_without_fetch(self):
        fake = FakeRateSource()
        with override_rate_source(fake):
            result = convert(Decimal("100"), "CZK", "CZK")

        self.assertEqual(result, Decimal("100"))
        self.assertEqual(fake.fetch_bulk_calls, [])

    def test_convert_with_stored_rate_returns_full_precision_product(self):
        self._seed_today_rates({"CZK": Decimal("25.123")})

        with override_rate_source(FakeRateSource()):
            result = convert(Decimal("100"), "EUR", "CZK")

        self.assertEqual(result, Decimal("100") * Decimal("25.123"))

    def test_second_get_rate_for_same_pair_does_not_invoke_rate_source(self):
        self._seed_today_rates({"CZK": Decimal("25.0")})
        fake = FakeRateSource()

        with override_rate_source(fake):
            first = get_rate("EUR", "CZK")
            second = get_rate("EUR", "CZK")

        self.assertEqual(first.rate, Decimal("25.0"))
        self.assertEqual(second.rate, Decimal("25.0"))
        self.assertEqual(fake.fetch_bulk_calls, [])

    def test_missing_stored_rate_raises_currency_conversion_error(self):
        fake = FakeRateSource(
            bulk_error=CurrencyConversionError("Failed to fetch bulk exchange rates"),
        )
        with override_rate_source(fake):
            with patch("financetracker.services.currency.ensure_sync_if_stale"):
                with self.assertRaises(CurrencyConversionError):
                    get_rate("EUR", "CZK")

    def test_same_currency_latest_rate_returns_one_without_fetch_or_db(self):
        fake = FakeRateSource()
        with override_rate_source(fake):
            result = get_rate("EUR", "EUR")

        self.assertEqual(result.rate, Decimal("1"))
        self.assertEqual(fake.fetch_bulk_calls, [])

    def test_mixed_case_currency_codes_normalized(self):
        self._seed_today_rates({"CZK": Decimal("25.0")})

        with override_rate_source(FakeRateSource()):
            mixed = get_rate("eur", "czk")
            upper = get_rate("EUR", "CZK")

        self.assertEqual(mixed.rate, upper.rate)

    def test_non_positive_amount_raises_value_error_without_fetch(self):
        fake = FakeRateSource()
        with override_rate_source(fake):
            with self.assertRaises(ValueError):
                convert(Decimal("0"), "EUR", "CZK")

        self.assertEqual(fake.fetch_bulk_calls, [])

    def test_get_supported_currencies_reads_from_metadata_without_fetch(self):
        metadata = SyncMetadata.get_singleton()
        metadata.supported_currencies = {
            "EUR": "Euro",
            "CZK": "Czech Koruna",
        }
        metadata.save()

        fake = FakeRateSource()
        with override_rate_source(fake):
            result = get_supported_currencies()

        self.assertEqual(result, {"EUR": "Euro", "CZK": "Czech Koruna"})
        self.assertEqual(fake.fetch_currencies_calls, 0)

    def test_get_supported_currencies_falls_back_to_rate_source_when_metadata_empty(self):
        fake = FakeRateSource(
            currencies={"EUR": "Euro", "CZK": "Czech Koruna"},
        )
        with override_rate_source(fake):
            result = get_supported_currencies()

        self.assertEqual(result, {"EUR": "Euro", "CZK": "Czech Koruna"})
        self.assertEqual(fake.fetch_currencies_calls, 1)

    def test_supported_currencies_rate_source_failure_raises_currency_conversion_error(self):
        fake = FakeRateSource(
            currencies_error=CurrencyConversionError("Failed to fetch supported currencies"),
        )
        with override_rate_source(fake):
            with self.assertRaises(CurrencyConversionError):
                get_supported_currencies()

    def test_past_date_fetches_bulk_snapshot_and_stores_under_requested_date(self):
        past_date = date.today() - timedelta(days=30)
        fake = FakeRateSource(
            rates_by_date={
                past_date: {"CZK": Decimal("25.5"), "USD": Decimal("1.1")},
            },
        )
        with override_rate_source(fake):
            result = get_rate("EUR", "CZK", on_date=past_date)

        self.assertEqual(result.rate, Decimal("25.5"))
        self.assertIsNone(result.stale_date)
        self.assertEqual(fake.fetch_bulk_calls, [past_date])
        stored = ExchangeRate.objects.get(quote_currency="CZK", rate_date=past_date)
        self.assertEqual(stored.rate, Decimal("25.5"))
        self.assertEqual(stored.base_currency, "EUR")

    def test_convert_with_on_date_uses_historical_rate(self):
        past_date = date.today() - timedelta(days=10)
        fake = FakeRateSource(
            rates_by_date={past_date: {"CZK": Decimal("25.0")}},
        )
        with override_rate_source(fake):
            result = convert(Decimal("100"), "EUR", "CZK", on_date=past_date)

        self.assertEqual(result, Decimal("2500"))
        self.assertEqual(fake.fetch_bulk_calls, [past_date])

    def test_weekend_date_walks_back_to_prior_published_bulk_snapshot(self):
        saturday = date(2025, 3, 15)
        friday = date(2025, 3, 14)
        fake = FakeRateSource(
            unavailable_dates=frozenset({saturday}),
            rates_by_date={friday: {"CZK": Decimal("25.1")}},
        )
        with override_rate_source(fake):
            result = get_rate("EUR", "CZK", on_date=saturday)

        self.assertEqual(result.rate, Decimal("25.1"))
        self.assertEqual(fake.fetch_bulk_calls, [saturday, friday])
        stored = ExchangeRate.objects.get(quote_currency="CZK", rate_date=saturday)
        self.assertEqual(stored.rate, Decimal("25.1"))

    def test_future_date_uses_stored_latest_rate(self):
        future_date = date.today() + timedelta(days=5)
        self._seed_today_rates({"CZK": Decimal("25.0")})
        fake = FakeRateSource()

        with override_rate_source(fake):
            result = get_rate("EUR", "CZK", on_date=future_date)

        self.assertEqual(result.rate, Decimal("25.0"))
        self.assertEqual(fake.fetch_bulk_calls, [])

    def test_today_date_uses_stored_latest_rate(self):
        self._seed_today_rates({"CZK": Decimal("25.0")})
        fake = FakeRateSource()

        with override_rate_source(fake):
            result = get_rate("EUR", "CZK", on_date=date.today())

        self.assertEqual(result.rate, Decimal("25.0"))
        self.assertEqual(fake.fetch_bulk_calls, [])

    def test_same_currency_with_on_date_skips_fetch(self):
        fake = FakeRateSource()
        with override_rate_source(fake):
            result = get_rate("EUR", "EUR", on_date=date.today() - timedelta(days=1))

        self.assertEqual(result.rate, Decimal("1"))
        self.assertEqual(fake.fetch_bulk_calls, [])

    def test_walk_back_exhausted_raises_currency_conversion_error(self):
        fake = FakeRateSource()
        with override_rate_source(fake):
            with self.assertRaises(CurrencyConversionError):
                get_rate("EUR", "CZK", on_date=date(2025, 3, 15))

        self.assertEqual(len(fake.fetch_bulk_calls), 8)

    def test_second_historical_get_rate_uses_db_without_fetch(self):
        past_date = date.today() - timedelta(days=30)
        fake = FakeRateSource(
            rates_by_date={past_date: {"CZK": Decimal("25.0")}},
        )
        with override_rate_source(fake):
            first = get_rate("EUR", "CZK", on_date=past_date)
            fake.fetch_bulk_calls.clear()
            second = get_rate("EUR", "CZK", on_date=past_date)

        self.assertEqual(first.rate, Decimal("25.0"))
        self.assertEqual(second.rate, Decimal("25.0"))
        self.assertEqual(fake.fetch_bulk_calls, [])

    def test_multiple_pairs_on_same_historical_date_share_one_bulk_fetch(self):
        past_date = date.today() - timedelta(days=30)
        fake = FakeRateSource(
            rates_by_date={
                past_date: {"USD": Decimal("1.1"), "CZK": Decimal("25.0")},
            },
        )
        with override_rate_source(fake):
            usd_czk = get_rate("USD", "CZK", on_date=past_date)
            eur_czk = get_rate("EUR", "CZK", on_date=past_date)

        self.assertEqual(usd_czk.rate, Decimal("25.0") / Decimal("1.1"))
        self.assertEqual(eur_czk.rate, Decimal("25.0"))
        self.assertEqual(fake.fetch_bulk_calls, [past_date])

    def test_historical_cross_derivation_from_stored_eur_rates(self):
        past_date = date.today() - timedelta(days=30)
        fetched_at = timezone.now()
        for quote_currency, rate in {"USD": Decimal("1.1"), "CZK": Decimal("25.0")}.items():
            ExchangeRate.objects.create(
                base_currency="EUR",
                quote_currency=quote_currency,
                rate_date=past_date,
                rate=rate,
                fetched_at=fetched_at,
            )

        fake = FakeRateSource()
        with override_rate_source(fake):
            result = get_rate("USD", "CZK", on_date=past_date)

        self.assertEqual(result.rate, Decimal("25.0") / Decimal("1.1"))
        self.assertEqual(fake.fetch_bulk_calls, [])

    def _seed_rates_for_date(
        self,
        rate_date: date,
        rates: dict[str, Decimal],
    ) -> None:
        fetched_at = timezone.now()
        for quote_currency, rate in rates.items():
            ExchangeRate.objects.create(
                base_currency="EUR",
                quote_currency=quote_currency,
                rate_date=rate_date,
                rate=rate,
                fetched_at=fetched_at,
            )

    def test_stale_fallback_returns_rate_with_stale_date_when_fetch_fails(self):
        yesterday = date.today() - timedelta(days=1)
        self._seed_rates_for_date(yesterday, {"CZK": Decimal("24.0")})
        fake = FakeRateSource(
            bulk_error=CurrencyConversionError("Failed to fetch bulk exchange rates"),
        )

        with override_rate_source(fake):
            with patch("financetracker.services.currency.ensure_sync_if_stale"):
                result = get_rate("EUR", "CZK")

        self.assertIsInstance(result, RateResult)
        self.assertEqual(result.rate, Decimal("24.0"))
        self.assertEqual(result.stale_date, yesterday)

    def test_true_unavailability_raises_when_fetch_fails_and_no_db_rows(self):
        fake = FakeRateSource(
            bulk_error=CurrencyConversionError("Failed to fetch bulk exchange rates"),
        )
        with override_rate_source(fake):
            with patch("financetracker.services.currency.ensure_sync_if_stale"):
                with self.assertRaises(CurrencyConversionError):
                    get_rate("EUR", "CZK")

    def test_startup_sync_lock_prevents_double_fetch(self):
        fake = FakeRateSource(
            rates_by_date={None: {"CZK": Decimal("25.0")}},
            currencies={"EUR": "Euro", "CZK": "Czech Koruna"},
        )
        with override_rate_source(fake):
            ensure_sync_if_stale()
            ensure_sync_if_stale()

        self.assertEqual(fake.fetch_bulk_calls, [None])
        self.assertEqual(fake.fetch_currencies_calls, 1)
        metadata = SyncMetadata.get_singleton()
        self.assertEqual(metadata.last_successful_sync_date, date.today())
        self.assertFalse(metadata.sync_in_progress)


class StartupSyncLockTests(TestCase):
    def test_skips_fetch_when_sync_already_in_progress(self):
        metadata = SyncMetadata.get_singleton()
        metadata.sync_in_progress = True
        metadata.save(update_fields=["sync_in_progress"])
        fake = FakeRateSource()

        with override_rate_source(fake):
            ensure_sync_if_stale()

        self.assertEqual(fake.fetch_bulk_calls, [])
        metadata.refresh_from_db()
        self.assertTrue(metadata.sync_in_progress)

    def test_releases_lock_after_failed_sync(self):
        fake = FakeRateSource(
            bulk_error=CurrencyConversionError("Failed to fetch bulk exchange rates"),
        )
        with override_rate_source(fake):
            ensure_sync_if_stale()

        metadata = SyncMetadata.get_singleton()
        self.assertIsNone(metadata.last_successful_sync_date)
        self.assertFalse(metadata.sync_in_progress)

    def test_ensure_rate_snapshots_fetches_each_missing_date_once(self):
        past = date.today() - timedelta(days=10)
        other_past = date.today() - timedelta(days=20)
        fake = FakeRateSource(
            rates_by_date={
                past: {"CZK": Decimal("25.0")},
                other_past: {"CZK": Decimal("25.0")},
            },
        )
        with override_rate_source(fake):
            ensure_rate_snapshots([past, other_past, past])

        self.assertEqual(set(fake.fetch_bulk_calls), {past, other_past})
        self.assertTrue(ExchangeRate.objects.filter(rate_date=past).exists())
        self.assertTrue(ExchangeRate.objects.filter(rate_date=other_past).exists())


class IncompleteSnapshotTests(TestCase):
    def test_partial_date_snapshot_is_refetched_for_missing_quote(self):
        """Alphabetical-prefix leftovers must not block a full bulk refill."""
        past_date = date.today() - timedelta(days=30)
        fetched_at = timezone.now()
        for quote in ["AED", "AFN", "ALL", "AMD"]:
            ExchangeRate.objects.create(
                base_currency="EUR",
                quote_currency=quote,
                rate_date=past_date,
                rate=Decimal("1.0"),
                fetched_at=fetched_at,
            )
        metadata = SyncMetadata.get_singleton()
        metadata.supported_currencies = {
            "EUR": "Euro",
            "AED": "UAE Dirham",
            "AFN": "Afghan Afghani",
            "ALL": "Albanian Lek",
            "AMD": "Armenian Dram",
            "CZK": "Czech Koruna",
            "USD": "US Dollar",
        }
        metadata.save(update_fields=["supported_currencies"])

        fake = FakeRateSource(
            rates_by_date={
                past_date: {
                    "AED": Decimal("4.0"),
                    "AFN": Decimal("80.0"),
                    "ALL": Decimal("100.0"),
                    "AMD": Decimal("420.0"),
                    "CZK": Decimal("25.0"),
                    "USD": Decimal("1.1"),
                },
            },
        )
        with override_rate_source(fake):
            result = get_rate("EUR", "CZK", on_date=past_date)

        self.assertEqual(result.rate, Decimal("25.0"))
        self.assertEqual(fake.fetch_bulk_calls, [past_date])
        self.assertEqual(
            ExchangeRate.objects.filter(rate_date=past_date).count(),
            6,
        )
        self.assertTrue(
            ExchangeRate.objects.filter(
                rate_date=past_date,
                quote_currency="CZK",
            ).exists()
        )
