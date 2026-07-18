from decimal import Decimal

from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

from financetracker.context_processors import display_locale


class DisplayLocaleContextProcessorTests(SimpleTestCase):
    def test_exposes_locale_from_accept_language(self):
        request = RequestFactory().get("/")
        request.META["HTTP_ACCEPT_LANGUAGE"] = "cs-CZ,cs;q=0.9"
        self.assertEqual(
            display_locale(request),
            {"display_locale": "cs"},
        )


class MoneyTemplateTagTests(SimpleTestCase):
    def test_money_tag_uses_display_locale(self):
        template = Template("{% load money %}{% money amount currency %}")
        rendered = template.render(
            Context(
                {
                    "amount": Decimal("1234.56"),
                    "currency": "CZK",
                    "display_locale": "cs",
                }
            )
        )
        self.assertEqual(rendered, "1\xa0234,56 CZK")

    def test_money_amount_tag_formats_number_only(self):
        template = Template("{% load money %}{% money_amount amount %}")
        rendered = template.render(
            Context(
                {
                    "amount": Decimal("1234.56"),
                    "display_locale": "en",
                }
            )
        )
        self.assertEqual(rendered, "1,234.56")

    def test_money_amount_accepts_decimal_places(self):
        template = Template("{% load money %}{% money_amount amount 4 %}")
        rendered = template.render(
            Context(
                {
                    "amount": Decimal("1.2345"),
                    "display_locale": "en",
                }
            )
        )
        self.assertEqual(rendered, "1.2345")

    def test_falls_back_when_display_locale_missing(self):
        template = Template("{% load money %}{% money amount currency %}")
        rendered = template.render(
            Context(
                {
                    "amount": Decimal("10.00"),
                    "currency": "EUR",
                }
            )
        )
        self.assertEqual(rendered, "10.00 EUR")
