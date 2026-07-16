from datetime import date, timedelta

import json
from decimal import Decimal
from unittest.mock import patch

import requests
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from financetracker.models import ExchangeRate, SyncMetadata
from financetracker.services.conversion_pair import (
    DEFAULT_PAIR,
    ConversionPair,
    resolve_conversion_pair,
)
from financetracker.services.currency import CurrencyConversionError, RateResult
from financetracker.tests.factories import DEFAULT_PASSWORD, create_user

SUPPORTED = {"CZK": "Czech Koruna", "EUR": "Euro", "BGN": "Bulgarian Lev", "USD": "US Dollar"}


class CurrencyConverterViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)

    def test_anonymous_user_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("currency_converter"))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('currency_converter')}",
        )

    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_first_get_uses_default_pair_and_shows_rate(self, mock_get_rate):
        response = self.client.get(reverse("currency_converter"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["from_currency"], "CZK")
        self.assertEqual(response.context["to_currency"], "EUR")
        self.assertEqual(response.context["rate"], Decimal("0.0401"))
        mock_get_rate.assert_called_once_with("CZK", "EUR")

    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_get_amount_query_param_repopulates_form_without_result(self, mock_get_rate):
        response = self.client.get(
            reverse("currency_converter"),
            {"amount": "500"},
        )

        self.assertEqual(response.context["form"].initial.get("amount"), "500")
        self.assertIsNone(response.context.get("converted_amount"))

    def test_post_to_page_view_is_not_allowed(self):
        response = self.client.post(
            reverse("currency_converter"),
            {"from_currency": "CZK", "to_currency": "EUR", "amount": "500"},
        )

        self.assertEqual(response.status_code, 405)

    @patch("financetracker.views.get_rate", side_effect=CurrencyConversionError("failed"))
    def test_get_rate_error_shows_message_and_keeps_form(self, mock_get_rate):
        response = self.client.get(reverse("currency_converter"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Couldn't fetch the exchange rate", html=False)
        self.assertIsNone(response.context.get("rate"))

    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_get_shell_exposes_interactive_client_markers(self, mock_get_rate):
        response = self.client.get(reverse("currency_converter"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="converter-form"')
        self.assertContains(response, reverse("converter_rate_api"))
        self.assertContains(response, reverse("converter_convert_api"))
        self.assertContains(response, 'id="converter-result-value"')
        self.assertContains(response, "converter-result-value--empty")
        content = response.content.decode()
        self.assertRegex(
            content,
            r'<form novalidate id="converter-form"[^>]*data-rate-url=',
        )
        self.assertNotContains(response, "converted_amount", html=False)

    def test_get_uses_stored_rates_without_mocking_get_rate(self):
        fetched_at = timezone.now()
        # Snapshot must be complete vs supported_currencies or latest-rate
        # lookup will treat it as partial and refetch from Frankfurter.
        for quote, rate in {
            "CZK": Decimal("25.0"),
            "BGN": Decimal("1.9558"),
            "USD": Decimal("1.1"),
        }.items():
            ExchangeRate.objects.create(
                base_currency="EUR",
                quote_currency=quote,
                rate_date=date.today(),
                rate=rate,
                fetched_at=fetched_at,
            )
        metadata = SyncMetadata.get_singleton()
        metadata.supported_currencies = SUPPORTED.copy()
        metadata.last_successful_sync_date = date.today()
        metadata.save()

        with patch(
            "financetracker.services.currency.requests.get",
            side_effect=AssertionError("stored rates must not hit the network"),
        ):
            response = self.client.get(
                reverse("currency_converter"),
                {"from": "CZK", "to": "EUR"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rate"], Decimal("1") / Decimal("25.0"))
        self.assertIsNone(response.context.get("rates_stale_date"))
    @patch("financetracker.views.get_rate")
    def test_get_shows_stale_rate_warning_when_rates_are_stale(self, mock_get_rate):
        yesterday = date.today() - timedelta(days=1)
        mock_get_rate.return_value = RateResult(
            rate=Decimal("0.0401"),
            stale_date=yesterday,
        )

        response = self.client.get(reverse("currency_converter"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rates_stale_date"], yesterday)
        self.assertContains(response, "Exchange rates from")
        self.assertContains(response, yesterday.isoformat())


class ConverterRateApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)

    def test_anonymous_user_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(
            reverse("converter_rate_api"),
            {"from": "CZK", "to": "EUR"},
        )
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('converter_rate_api')}%3Ffrom%3DCZK%26to%3DEUR",
        )

    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.04012345")))
    def test_valid_pair_returns_rate_json(self, mock_get_rate):
        response = self.client.get(
            reverse("converter_rate_api"),
            {"from": "CZK", "to": "EUR"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, {"from": "CZK", "to": "EUR", "rate": "0.0401"})
        mock_get_rate.assert_called_once_with("CZK", "EUR")

    def test_valid_pair_returns_rate_from_stored_rates(self):
        fetched_at = timezone.now()
        for quote, rate in {
            "CZK": Decimal("25.0"),
            "BGN": Decimal("1.9558"),
            "USD": Decimal("1.1"),
        }.items():
            ExchangeRate.objects.create(
                base_currency="EUR",
                quote_currency=quote,
                rate_date=date.today(),
                rate=rate,
                fetched_at=fetched_at,
            )
        metadata = SyncMetadata.get_singleton()
        metadata.supported_currencies = SUPPORTED.copy()
        metadata.last_successful_sync_date = date.today()
        metadata.save()

        with patch(
            "financetracker.services.currency.requests.get",
            side_effect=AssertionError("stored rates must not hit the network"),
        ):
            response = self.client.get(
                reverse("converter_rate_api"),
                {"from": "CZK", "to": "EUR"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"from": "CZK", "to": "EUR", "rate": "0.0400"},
        )

    def test_valid_pair_returns_stale_rate_from_stored_rates(self):
        yesterday = date.today() - timedelta(days=1)
        fetched_at = timezone.now()
        ExchangeRate.objects.create(
            base_currency="EUR",
            quote_currency="CZK",
            rate_date=yesterday,
            rate=Decimal("25.0"),
            fetched_at=fetched_at,
        )

        with patch(
            "financetracker.services.currency.ensure_sync_if_stale",
        ), patch(
            "financetracker.services.currency.requests.get",
            side_effect=requests.RequestException("network down"),
        ):
            response = self.client.get(
                reverse("converter_rate_api"),
                {"from": "CZK", "to": "EUR"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["from"], "CZK")
        self.assertEqual(data["to"], "EUR")
        self.assertEqual(data["rate"], "0.0400")
        self.assertEqual(data["rates_stale_date"], yesterday.isoformat())

    @patch("financetracker.views.get_rate")
    def test_invalid_currency_returns_400(self, mock_get_rate):
        response = self.client.get(
            reverse("converter_rate_api"),
            {"from": "FAKE", "to": "EUR"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        mock_get_rate.assert_not_called()

    @patch("financetracker.views.get_rate", side_effect=CurrencyConversionError("failed"))
    def test_conversion_error_returns_error_json(self, mock_get_rate):
        response = self.client.get(
            reverse("converter_rate_api"),
            {"from": "CZK", "to": "EUR"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())


class ConverterConvertApiTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.user = create_user()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)

    def _post_convert(self, payload):
        self.client.get(reverse("currency_converter"))
        csrf_token = self.client.cookies["csrftoken"].value
        return self.client.post(
            reverse("converter_convert_api"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

    def test_anonymous_user_redirected_to_login(self):
        self.client.logout()
        self.client.get(reverse("login"))
        csrf_token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            reverse("converter_convert_api"),
            data=json.dumps({"from": "CZK", "to": "EUR", "amount": "100"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('converter_convert_api')}",
        )

    @patch("financetracker.views.convert", return_value=Decimal("20.050000"))
    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_success_returns_conversion_json_and_remembers_pair(
        self, mock_get_rate, mock_convert
    ):
        response = self._post_convert({"from": "USD", "to": "CZK", "amount": "500"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data,
            {
                "from": "USD",
                "to": "CZK",
                "rate": "0.0401",
                "converted_amount": "20.05",
            },
        )
        mock_convert.assert_called_once_with(Decimal("500"), "USD", "CZK")
        self.assertEqual(
            resolve_conversion_pair(self.client.session, SUPPORTED),
            ConversionPair("USD", "CZK"),
        )

    @patch("financetracker.views.convert", return_value=Decimal("20.050000"))
    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_success_remembers_pair_for_next_page_load(
        self, mock_get_rate, mock_convert
    ):
        self._post_convert({"from": "EUR", "to": "BGN", "amount": "100"})

        response = self.client.get(reverse("currency_converter"))

        self.assertEqual(response.context["from_currency"], "EUR")
        self.assertEqual(response.context["to_currency"], "BGN")

    @patch("financetracker.views.convert")
    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_empty_amount_returns_400_without_calling_convert(self, mock_get_rate, mock_convert):
        response = self._post_convert({"from": "CZK", "to": "EUR", "amount": ""})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        mock_convert.assert_not_called()
        self.assertEqual(
            resolve_conversion_pair(self.client.session, SUPPORTED),
            DEFAULT_PAIR,
        )

    @patch("financetracker.views.convert")
    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_zero_amount_returns_400_without_calling_convert(self, mock_get_rate, mock_convert):
        response = self._post_convert({"from": "CZK", "to": "EUR", "amount": "0"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        mock_convert.assert_not_called()

    @patch("financetracker.views.convert")
    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_negative_amount_returns_400_without_calling_convert(
        self, mock_get_rate, mock_convert
    ):
        response = self._post_convert({"from": "CZK", "to": "EUR", "amount": "-10"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        mock_convert.assert_not_called()

    @patch("financetracker.views.convert", side_effect=CurrencyConversionError("failed"))
    @patch("financetracker.views.get_rate", return_value=RateResult(rate=Decimal("0.0401")))
    def test_conversion_error_returns_error_json_without_remembering_pair(
        self, mock_get_rate, mock_convert
    ):
        response = self._post_convert({"from": "CZK", "to": "EUR", "amount": "100"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())
        self.assertEqual(
            resolve_conversion_pair(self.client.session, SUPPORTED),
            DEFAULT_PAIR,
        )
