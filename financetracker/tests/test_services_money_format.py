from decimal import Decimal

from django.test import SimpleTestCase

from financetracker.services.money_format import format_amount, format_money, locale_from_accept_language


class LocaleFromAcceptLanguageTests(SimpleTestCase):
    def test_prefers_first_supported_language(self):
        self.assertEqual(
            locale_from_accept_language("cs-CZ,cs;q=0.9,en;q=0.8"),
            "cs",
        )

    def test_falls_back_to_language_code_when_header_missing(self):
        self.assertEqual(locale_from_accept_language(None), "en-us")
        self.assertEqual(locale_from_accept_language(""), "en-us")

    def test_skips_unsupported_tags(self):
        self.assertEqual(locale_from_accept_language("xx-YY,en-GB;q=0.8"), "en-gb")

    def test_falls_back_when_no_supported_language(self):
        self.assertEqual(locale_from_accept_language("xx-YY,zz-ZZ"), "en-us")


class FormatAmountTests(SimpleTestCase):
    def test_formats_czech_grouping_and_decimal(self):
        self.assertEqual(format_amount(Decimal("1234.56"), locale="cs"), "1\xa0234,56")

    def test_formats_us_english_grouping_and_decimal(self):
        self.assertEqual(format_amount(Decimal("1234.56"), locale="en"), "1,234.56")

    def test_respects_decimal_places(self):
        self.assertEqual(
            format_amount(Decimal("1.2345"), locale="en", decimal_places=4),
            "1.2345",
        )


class FormatMoneyTests(SimpleTestCase):
    def test_appends_currency_code(self):
        self.assertEqual(
            format_money(Decimal("1234.56"), "CZK", locale="cs"),
            "1\xa0234,56 CZK",
        )

    def test_normalizes_currency_to_uppercase(self):
        self.assertEqual(
            format_money(Decimal("10.00"), "eur", locale="en"),
            "10.00 EUR",
        )
