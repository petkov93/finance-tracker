from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from financetracker.models import ExchangeRate, SyncMetadata
from financetracker.services.currency import (
    PAST_RATE_CACHE_TTL_SECONDS,
    CurrencyConversionError,
    convert,
    get_rate,
    get_supported_currencies,
    sync_latest_rates,
)


class CurrencyServiceTests(TestCase):
    def setUp(self):
        cache.clear()

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

    @patch("financetracker.services.currency.requests.get")
    def test_sync_latest_rates_upserts_eur_base_rows_for_today(self, mock_get):
        rates_response = MagicMock()
        rates_response.raise_for_status.return_value = None
        rates_response.json.return_value = [
            {
                "date": date.today().isoformat(),
                "base": "EUR",
                "quote": "USD",
                "rate": 1.1,
            },
            {
                "date": date.today().isoformat(),
                "base": "EUR",
                "quote": "CZK",
                "rate": 25.0,
            },
        ]

        currencies_response = MagicMock()
        currencies_response.raise_for_status.return_value = None
        currencies_response.json.return_value = [
            {"iso_code": "EUR", "name": "Euro"},
            {"iso_code": "USD", "name": "US Dollar"},
            {"iso_code": "CZK", "name": "Czech Koruna"},
        ]
        mock_get.side_effect = [rates_response, currencies_response]

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

        result = get_rate("USD", "CZK")

        self.assertEqual(result, Decimal("25.0") / Decimal("1.1"))

    @patch("financetracker.services.currency.requests.get")
    def test_same_currency_conversion_returns_amount_without_http(self, mock_get):
        result = convert(Decimal("100"), "CZK", "CZK")

        self.assertEqual(result, Decimal("100"))
        mock_get.assert_not_called()

    def test_convert_with_stored_rate_returns_full_precision_product(self):
        self._seed_today_rates({"CZK": Decimal("25.123")})

        result = convert(Decimal("100"), "EUR", "CZK")

        self.assertEqual(result, Decimal("100") * Decimal("25.123"))

    def test_second_get_rate_for_same_pair_does_not_invoke_http(self):
        self._seed_today_rates({"CZK": Decimal("25.0")})

        with patch("financetracker.services.currency.requests.get") as mock_get:
            first = get_rate("EUR", "CZK")
            second = get_rate("EUR", "CZK")

        self.assertEqual(first, Decimal("25.0"))
        self.assertEqual(second, Decimal("25.0"))
        mock_get.assert_not_called()

    @patch("financetracker.services.currency.requests.get")
    def test_missing_stored_rate_raises_currency_conversion_error(self, mock_get):
        with self.assertRaises(CurrencyConversionError):
            get_rate("EUR", "CZK")

        mock_get.assert_not_called()

    def test_same_currency_latest_rate_returns_one_without_http_or_db(self):
        with patch("financetracker.services.currency.requests.get") as mock_get:
            result = get_rate("EUR", "EUR")

        self.assertEqual(result, Decimal("1"))
        mock_get.assert_not_called()

    def test_mixed_case_currency_codes_normalized(self):
        self._seed_today_rates({"CZK": Decimal("25.0")})

        mixed = get_rate("eur", "czk")
        upper = get_rate("EUR", "CZK")

        self.assertEqual(mixed, upper)

    @patch("financetracker.services.currency.requests.get")
    def test_non_positive_amount_raises_value_error_without_api_call(self, mock_get):
        with self.assertRaises(ValueError):
            convert(Decimal("0"), "EUR", "CZK")

        mock_get.assert_not_called()

    def test_get_supported_currencies_reads_from_metadata_without_http(self):
        metadata = SyncMetadata.get_singleton()
        metadata.supported_currencies = {
            "EUR": "Euro",
            "CZK": "Czech Koruna",
        }
        metadata.save()

        with patch("financetracker.services.currency.requests.get") as mock_get:
            result = get_supported_currencies()

        self.assertEqual(result, {"EUR": "Euro", "CZK": "Czech Koruna"})
        mock_get.assert_not_called()

    @patch("financetracker.services.currency.requests.get")
    def test_get_supported_currencies_falls_back_to_api_when_metadata_empty(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {"iso_code": "EUR", "name": "Euro"},
            {"iso_code": "CZK", "name": "Czech Koruna"},
        ]
        mock_get.return_value = mock_response

        result = get_supported_currencies()

        self.assertEqual(result, {"EUR": "Euro", "CZK": "Czech Koruna"})
        mock_get.assert_called_once()

    @patch("financetracker.services.currency.requests.get")
    def test_supported_currencies_api_failure_raises_currency_conversion_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("network down")

        with self.assertRaises(CurrencyConversionError):
            get_supported_currencies()

    @patch("financetracker.services.currency.requests.get")
    def test_past_date_uses_historical_endpoint(self, mock_get):
        past_date = date.today() - timedelta(days=30)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.5}
        mock_get.return_value = mock_response

        result = get_rate("EUR", "CZK", on_date=past_date)

        self.assertEqual(result, Decimal("25.5"))
        mock_get.assert_called_once_with(
            f"https://api.frankfurter.dev/v2/rate/EUR/CZK/{past_date.isoformat()}",
            timeout=3,
        )

    @patch("financetracker.services.currency.requests.get")
    def test_convert_with_on_date_uses_historical_rate(self, mock_get):
        past_date = date.today() - timedelta(days=10)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.0}
        mock_get.return_value = mock_response

        result = convert(Decimal("100"), "EUR", "CZK", on_date=past_date)

        self.assertEqual(result, Decimal("2500"))
        mock_get.assert_called_once()

    @patch("financetracker.services.currency.requests.get")
    def test_weekend_date_walks_back_to_prior_published_rate(self, mock_get):
        saturday = date(2025, 3, 15)
        friday = date(2025, 3, 14)

        missing = MagicMock()
        missing.status_code = 404

        found = MagicMock()
        found.status_code = 200
        found.raise_for_status.return_value = None
        found.json.return_value = {"rate": 25.1}
        mock_get.side_effect = [missing, found]

        result = get_rate("EUR", "CZK", on_date=saturday)

        self.assertEqual(result, Decimal("25.1"))
        self.assertEqual(mock_get.call_count, 2)
        self.assertIn(
            f"/EUR/CZK/{saturday.isoformat()}",
            mock_get.call_args_list[0].args[0],
        )
        self.assertIn(
            f"/EUR/CZK/{friday.isoformat()}",
            mock_get.call_args_list[1].args[0],
        )

    def test_future_date_uses_stored_latest_rate(self):
        future_date = date.today() + timedelta(days=5)
        self._seed_today_rates({"CZK": Decimal("25.0")})

        with patch("financetracker.services.currency.requests.get") as mock_get:
            result = get_rate("EUR", "CZK", on_date=future_date)

        self.assertEqual(result, Decimal("25.0"))
        mock_get.assert_not_called()

    def test_today_date_uses_stored_latest_rate(self):
        self._seed_today_rates({"CZK": Decimal("25.0")})

        with patch("financetracker.services.currency.requests.get") as mock_get:
            result = get_rate("EUR", "CZK", on_date=date.today())

        self.assertEqual(result, Decimal("25.0"))
        mock_get.assert_not_called()

    @patch("financetracker.services.currency.cache.set")
    @patch("financetracker.services.currency.requests.get")
    def test_past_rate_cached_with_date_key_and_immutable_ttl(self, mock_get, mock_cache_set):
        past_date = date.today() - timedelta(days=30)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.0}
        mock_get.return_value = mock_response

        get_rate("EUR", "CZK", on_date=past_date)

        mock_cache_set.assert_called_once_with(
            f"currency_rate_EUR_CZK_{past_date.isoformat()}",
            "25.0",
            PAST_RATE_CACHE_TTL_SECONDS,
        )

    @patch("financetracker.services.currency.requests.get")
    def test_same_currency_with_on_date_skips_http(self, mock_get):
        result = get_rate("EUR", "EUR", on_date=date.today() - timedelta(days=1))

        self.assertEqual(result, Decimal("1"))
        mock_get.assert_not_called()

    @patch("financetracker.services.currency.cache.set")
    @patch("financetracker.services.currency.requests.get")
    def test_walk_back_rate_cached_under_requested_date_key(self, mock_get, mock_cache_set):
        saturday = date(2025, 3, 15)

        missing = MagicMock()
        missing.status_code = 404

        found = MagicMock()
        found.status_code = 200
        found.raise_for_status.return_value = None
        found.json.return_value = {"rate": 25.1}
        mock_get.side_effect = [missing, found]

        get_rate("EUR", "CZK", on_date=saturday)

        mock_cache_set.assert_called_once_with(
            f"currency_rate_EUR_CZK_{saturday.isoformat()}",
            "25.1",
            PAST_RATE_CACHE_TTL_SECONDS,
        )

    @patch("financetracker.services.currency.requests.get")
    def test_walk_back_exhausted_raises_currency_conversion_error(self, mock_get):
        missing = MagicMock()
        missing.status_code = 404
        mock_get.return_value = missing

        with self.assertRaises(CurrencyConversionError):
            get_rate("EUR", "CZK", on_date=date(2025, 3, 15))

        self.assertEqual(mock_get.call_count, 8)

    @patch("financetracker.services.currency.requests.get")
    def test_historical_cache_hit_avoids_second_http_request(self, mock_get):
        past_date = date.today() - timedelta(days=30)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.0}
        mock_get.return_value = mock_response

        first = get_rate("EUR", "CZK", on_date=past_date)
        second = get_rate("EUR", "CZK", on_date=past_date)

        self.assertEqual(first, Decimal("25.0"))
        self.assertEqual(second, Decimal("25.0"))
        mock_get.assert_called_once()
