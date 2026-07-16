from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

from financetracker.services.frankfurter_rate_source import (
    FRANKFURTER_API_BASE,
    FrankfurterRateSource,
    REQUEST_TIMEOUT_SECONDS,
)
from financetracker.services.rate_source import CurrencyConversionError, RateNotAvailableForDate


class FrankfurterRateSourceTests(SimpleTestCase):
    def setUp(self):
        self.source = FrankfurterRateSource()

    @patch("financetracker.services.frankfurter_rate_source.requests.get")
    def test_fetch_bulk_rates_parses_eur_quotes(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {"date": "2025-01-01", "base": "EUR", "quote": "USD", "rate": 1.1},
            {"date": "2025-01-01", "base": "EUR", "quote": "CZK", "rate": 25.0},
        ]
        mock_get.return_value = mock_response

        rates = self.source.fetch_bulk_rates(on_date=date(2025, 1, 1))

        self.assertEqual(rates, {"USD": Decimal("1.1"), "CZK": Decimal("25.0")})
        mock_get.assert_called_once_with(
            f"{FRANKFURTER_API_BASE}/v2/rates?date=2025-01-01",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    @patch("financetracker.services.frankfurter_rate_source.requests.get")
    def test_fetch_bulk_rates_without_date_uses_latest_endpoint(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {"date": date.today().isoformat(), "base": "EUR", "quote": "CZK", "rate": 25.0},
        ]
        mock_get.return_value = mock_response

        rates = self.source.fetch_bulk_rates()

        self.assertEqual(rates, {"CZK": Decimal("25.0")})
        mock_get.assert_called_once_with(
            f"{FRANKFURTER_API_BASE}/v2/rates",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    @patch("financetracker.services.frankfurter_rate_source.requests.get")
    def test_fetch_bulk_rates_404_raises_rate_not_available(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        with self.assertRaises(RateNotAvailableForDate):
            self.source.fetch_bulk_rates(on_date=date(2025, 3, 15))

    @patch("financetracker.services.frankfurter_rate_source.requests.get")
    def test_fetch_bulk_rates_network_failure_raises_conversion_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("network down")

        with self.assertRaises(CurrencyConversionError):
            self.source.fetch_bulk_rates()

    @patch("financetracker.services.frankfurter_rate_source.requests.get")
    def test_fetch_supported_currencies_parses_iso_codes(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {"iso_code": "EUR", "name": "Euro"},
            {"iso_code": "CZK", "name": "Czech Koruna"},
        ]
        mock_get.return_value = mock_response

        currencies = self.source.fetch_supported_currencies()

        self.assertEqual(currencies, {"EUR": "Euro", "CZK": "Czech Koruna"})
        mock_get.assert_called_once_with(
            f"{FRANKFURTER_API_BASE}/v2/currencies",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    @patch("financetracker.services.frankfurter_rate_source.requests.get")
    def test_fetch_supported_currencies_network_failure_raises_conversion_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("network down")

        with self.assertRaises(CurrencyConversionError):
            self.source.fetch_supported_currencies()
