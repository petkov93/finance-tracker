from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import TestCase

from financetracker.services.currency import (
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
