from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import TestCase

from financetracker.services.currency import (
    PAST_RATE_CACHE_TTL_SECONDS,
    RATE_CACHE_TTL_SECONDS,
    CurrencyConversionError,
    convert,
    get_rate,
    get_supported_currencies,
)


class CurrencyServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("financetracker.services.currency.requests.get")
    def test_same_currency_conversion_returns_amount_without_http(self, mock_get):
        result = convert(Decimal("100"), "CZK", "CZK")

        self.assertEqual(result, Decimal("100"))
        mock_get.assert_not_called()

    @patch("financetracker.services.currency.requests.get")
    def test_convert_with_mocked_rate_returns_full_precision_product(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.123}
        mock_get.return_value = mock_response

        result = convert(Decimal("100"), "EUR", "CZK")

        self.assertEqual(result, Decimal("100") * Decimal("25.123"))
        mock_get.assert_called_once()

    @patch("financetracker.services.currency.requests.get")
    def test_cache_hit_avoids_second_http_request(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.0}
        mock_get.return_value = mock_response

        first = get_rate("EUR", "CZK")
        second = get_rate("EUR", "CZK")

        self.assertEqual(first, Decimal("25.0"))
        self.assertEqual(second, Decimal("25.0"))
        mock_get.assert_called_once()

    @patch("financetracker.services.currency.requests.get")
    def test_api_failure_raises_currency_conversion_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("network down")

        with self.assertRaises(CurrencyConversionError):
            get_rate("EUR", "CZK")

    @patch("financetracker.services.currency.requests.get")
    def test_malformed_response_raises_currency_conversion_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        with self.assertRaises(CurrencyConversionError):
            get_rate("EUR", "CZK")

    @patch("financetracker.services.currency.requests.get")
    def test_mixed_case_currency_codes_normalized(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.0}
        mock_get.return_value = mock_response

        mixed = get_rate("eur", "czk")
        cache.clear()
        mock_get.reset_mock()
        mock_get.return_value = mock_response

        upper = get_rate("EUR", "CZK")

        self.assertEqual(mixed, upper)

    @patch("financetracker.services.currency.requests.get")
    def test_non_positive_amount_raises_value_error_without_api_call(self, mock_get):
        with self.assertRaises(ValueError):
            convert(Decimal("0"), "EUR", "CZK")

        mock_get.assert_not_called()

    @patch("financetracker.services.currency.requests.get")
    def test_get_supported_currencies_returns_code_name_mapping(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {"iso_code": "EUR", "name": "Euro"},
            {"iso_code": "CZK", "name": "Czech Koruna"},
        ]
        mock_get.return_value = mock_response

        result = get_supported_currencies()

        self.assertEqual(result, {"EUR": "Euro", "CZK": "Czech Koruna"})

    @patch("financetracker.services.currency.requests.get")
    def test_supported_currencies_cache_hit_avoids_second_http_request(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [{"iso_code": "EUR", "name": "Euro"}]
        mock_get.return_value = mock_response

        get_supported_currencies()
        get_supported_currencies()

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
            timeout=10,
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

    @patch("financetracker.services.currency.requests.get")
    def test_future_date_uses_latest_endpoint(self, mock_get):
        future_date = date.today() + timedelta(days=5)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.0}
        mock_get.return_value = mock_response

        result = get_rate("EUR", "CZK", on_date=future_date)

        self.assertEqual(result, Decimal("25.0"))
        mock_get.assert_called_once_with(
            "https://api.frankfurter.dev/v2/rate/EUR/CZK",
            timeout=10,
        )

    @patch("financetracker.services.currency.requests.get")
    def test_today_date_uses_latest_endpoint(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.0}
        mock_get.return_value = mock_response

        result = get_rate("EUR", "CZK", on_date=date.today())

        self.assertEqual(result, Decimal("25.0"))
        mock_get.assert_called_once_with(
            "https://api.frankfurter.dev/v2/rate/EUR/CZK",
            timeout=10,
        )

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

    @patch("financetracker.services.currency.cache.set")
    @patch("financetracker.services.currency.requests.get")
    def test_latest_rate_cached_with_pair_key_and_24h_ttl(self, mock_get, mock_cache_set):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rate": 25.0}
        mock_get.return_value = mock_response

        get_rate("EUR", "CZK")

        mock_cache_set.assert_called_once_with(
            "currency_rate_EUR_CZK",
            "25.0",
            RATE_CACHE_TTL_SECONDS,
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
