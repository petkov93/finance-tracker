from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.services.currency import CurrencyConversionError
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

    @patch("financetracker.views.get_rate", return_value=Decimal("0.0401"))
    def test_first_get_uses_default_pair_and_shows_rate(self, mock_get_rate):
        response = self.client.get(reverse("currency_converter"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["from_currency"], "CZK")
        self.assertEqual(response.context["to_currency"], "EUR")
        self.assertEqual(response.context["rate"], Decimal("0.0401"))
        mock_get_rate.assert_called_once_with("CZK", "EUR")

    @patch("financetracker.views.get_rate", return_value=Decimal("1.9558"))
    def test_get_uses_session_last_used_pair(self, mock_get_rate):
        session = self.client.session
        session["converter_from_currency"] = "EUR"
        session["converter_to_currency"] = "BGN"
        session.save()

        response = self.client.get(reverse("currency_converter"))

        self.assertEqual(response.context["from_currency"], "EUR")
        self.assertEqual(response.context["to_currency"], "BGN")
        mock_get_rate.assert_called_once_with("EUR", "BGN")

    @patch("financetracker.views.get_rate", return_value=Decimal("1.10"))
    def test_get_url_params_override_session(self, mock_get_rate):
        session = self.client.session
        session["converter_from_currency"] = "EUR"
        session["converter_to_currency"] = "BGN"
        session.save()

        response = self.client.get(
            reverse("currency_converter"),
            {"from": "USD", "to": "EUR"},
        )

        self.assertEqual(response.context["from_currency"], "USD")
        self.assertEqual(response.context["to_currency"], "EUR")
        mock_get_rate.assert_called_once_with("USD", "EUR")

    @patch("financetracker.views.get_rate", return_value=Decimal("0.0401"))
    def test_get_invalid_currency_falls_back_to_defaults(self, mock_get_rate):
        response = self.client.get(
            reverse("currency_converter"),
            {"from": "FAKE", "to": "FAKE"},
        )

        self.assertEqual(response.context["from_currency"], "CZK")
        self.assertEqual(response.context["to_currency"], "EUR")
        mock_get_rate.assert_called_once_with("CZK", "EUR")

    @patch("financetracker.views.get_rate", return_value=Decimal("0.0401"))
    def test_get_amount_query_param_repopulates_form_without_result(self, mock_get_rate):
        response = self.client.get(
            reverse("currency_converter"),
            {"amount": "500"},
        )

        self.assertEqual(response.context["form"].initial.get("amount"), "500")
        self.assertIsNone(response.context.get("converted_amount"))

    @patch("financetracker.views.convert", return_value=Decimal("20.050000"))
    @patch("financetracker.views.get_rate", return_value=Decimal("0.0401"))
    def test_post_success_shows_result_and_updates_session(self, mock_get_rate, mock_convert):
        response = self.client.post(
            reverse("currency_converter"),
            {"from_currency": "CZK", "to_currency": "EUR", "amount": "500"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["converted_amount"], Decimal("20.05"))
        mock_convert.assert_called_once_with(Decimal("500"), "CZK", "EUR")
        self.assertEqual(self.client.session["converter_from_currency"], "CZK")
        self.assertEqual(self.client.session["converter_to_currency"], "EUR")

    @patch("financetracker.views.convert")
    @patch("financetracker.views.get_rate", return_value=Decimal("0.0401"))
    def test_post_empty_amount_shows_validation_error(self, mock_get_rate, mock_convert):
        response = self.client.post(
            reverse("currency_converter"),
            {"from_currency": "CZK", "to_currency": "EUR", "amount": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter an amount to convert.")
        mock_convert.assert_not_called()
        self.assertNotIn("converter_from_currency", self.client.session)

    @patch("financetracker.views.convert")
    @patch("financetracker.views.get_rate", return_value=Decimal("0.0401"))
    def test_post_zero_amount_shows_validation_error(self, mock_get_rate, mock_convert):
        response = self.client.post(
            reverse("currency_converter"),
            {"from_currency": "CZK", "to_currency": "EUR", "amount": "0"},
        )

        self.assertContains(response, "Amount must be greater than zero.")
        mock_convert.assert_not_called()

    @patch("financetracker.views.convert", side_effect=CurrencyConversionError("failed"))
    @patch("financetracker.views.get_rate", return_value=Decimal("0.0401"))
    def test_post_conversion_error_shows_message_without_session_update(
        self, mock_get_rate, mock_convert
    ):
        response = self.client.post(
            reverse("currency_converter"),
            {"from_currency": "CZK", "to_currency": "EUR", "amount": "100"},
        )

        self.assertContains(response, "Couldn't convert", html=False)
        self.assertNotIn("converter_from_currency", self.client.session)

    @patch("financetracker.views.get_rate", side_effect=CurrencyConversionError("failed"))
    def test_get_rate_error_shows_message_and_keeps_form(self, mock_get_rate):
        response = self.client.get(reverse("currency_converter"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Couldn't fetch the exchange rate", html=False)
        self.assertIsNone(response.context.get("rate"))

    @patch("financetracker.views.convert")
    @patch("financetracker.views.get_rate", return_value=Decimal("0.0401"))
    def test_post_negative_amount_shows_validation_error(self, mock_get_rate, mock_convert):
        response = self.client.post(
            reverse("currency_converter"),
            {"from_currency": "CZK", "to_currency": "EUR", "amount": "-10"},
        )

        self.assertContains(response, "Amount must be greater than zero.")
        mock_convert.assert_not_called()
