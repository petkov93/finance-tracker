from django.test import TestCase

from financetracker.forms import build_currency_choices


class BuildCurrencyChoicesTests(TestCase):
    def test_common_currencies_optgroup_then_all_alphabetically(self):
        supported = {
            "AUD": "Australian Dollar",
            "CNY": "Chinese Yuan",
            "CZK": "Czech Koruna",
            "EUR": "Euro",
            "GBP": "British Pound",
            "JPY": "Japanese Yen",
            "USD": "US Dollar",
            "ZAR": "South African Rand",
        }

        choices = build_currency_choices(supported)

        self.assertEqual(
            choices,
            [
                (
                    "Common currencies",
                    [
                        ("CZK", "CZK — Czech Koruna"),
                        ("USD", "USD — US Dollar"),
                        ("EUR", "EUR — Euro"),
                        ("JPY", "JPY — Japanese Yen"),
                        ("GBP", "GBP — British Pound"),
                        ("CNY", "CNY — Chinese Yuan"),
                    ],
                ),
                (
                    "All currencies",
                    [
                        ("AUD", "AUD — Australian Dollar"),
                        ("CNY", "CNY — Chinese Yuan"),
                        ("CZK", "CZK — Czech Koruna"),
                        ("EUR", "EUR — Euro"),
                        ("GBP", "GBP — British Pound"),
                        ("JPY", "JPY — Japanese Yen"),
                        ("USD", "USD — US Dollar"),
                        ("ZAR", "ZAR — South African Rand"),
                    ],
                ),
            ],
        )

    def test_omits_unsupported_common_currencies_and_hides_empty_group(self):
        supported = {
            "AUD": "Australian Dollar",
            "ZAR": "South African Rand",
        }

        choices = build_currency_choices(supported)

        self.assertEqual(
            choices,
            [
                (
                    "All currencies",
                    [
                        ("AUD", "AUD — Australian Dollar"),
                        ("ZAR", "ZAR — South African Rand"),
                    ],
                ),
            ],
        )
