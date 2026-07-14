from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from financetracker.services.currency import CurrencyConversionError
from financetracker.services.display_conversion import convert_for_display
from financetracker.tests.factories import create_transaction, create_user


class DisplayConversionTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_same_currency_row_shows_single_amount(self):
        transaction = create_transaction(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
        )

        result = convert_for_display([transaction], "CZK")

        row = result.rows[0]
        self.assertEqual(row.primary_amount, Decimal("100.00"))
        self.assertEqual(row.primary_currency, "CZK")
        self.assertFalse(row.show_native_footnote)
        self.assertFalse(result.conversion_degraded)

    def test_different_currency_row_shows_converted_primary_and_native_footnote(self):
        past = date.today() - timedelta(days=7)
        transaction = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            transaction_date=past,
        )
        rates = {(("EUR", "CZK", past)): Decimal("25.00")}

        with patch(
            "financetracker.services.display_conversion.get_rate",
            side_effect=lambda f, t, on_date=None: rates[(f, t, on_date)],
        ):
            result = convert_for_display([transaction], "CZK")

        row = result.rows[0]
        self.assertEqual(row.primary_amount, Decimal("250.00"))
        self.assertEqual(row.primary_currency, "CZK")
        self.assertEqual(row.native_amount, Decimal("10.00"))
        self.assertEqual(row.native_currency, "EUR")
        self.assertTrue(row.show_native_footnote)
        self.assertFalse(result.conversion_degraded)

    @patch("financetracker.services.display_conversion.get_rate")
    def test_batches_unique_pair_date_rate_lookups(self, mock_get_rate):
        past = date.today() - timedelta(days=3)
        other_past = date.today() - timedelta(days=5)
        mock_get_rate.return_value = Decimal("25.00")

        transactions = [
            create_transaction(
                self.user,
                amount=Decimal("10.00"),
                currency="EUR",
                transaction_date=past,
                description="a",
            ),
            create_transaction(
                self.user,
                amount=Decimal("20.00"),
                currency="EUR",
                transaction_date=past,
                description="b",
            ),
            create_transaction(
                self.user,
                amount=Decimal("5.00"),
                currency="USD",
                transaction_date=other_past,
                description="c",
            ),
        ]

        convert_for_display(transactions, "CZK")

        self.assertEqual(mock_get_rate.call_count, 2)
        mock_get_rate.assert_any_call("EUR", "CZK", on_date=past)
        mock_get_rate.assert_any_call("USD", "CZK", on_date=other_past)

    def test_totals_sum_converted_amounts(self):
        past = date.today() - timedelta(days=7)
        income = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type="income",
            transaction_date=past,
        )
        expense = create_transaction(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
            type="expense",
            transaction_date=past,
        )
        rates = {(("EUR", "CZK", past)): Decimal("25.00")}

        with patch(
            "financetracker.services.display_conversion.get_rate",
            side_effect=lambda f, t, on_date=None: rates[(f, t, on_date)],
        ):
            result = convert_for_display(
                [income, expense],
                "CZK",
                totals_transactions=[income, expense],
            )

        self.assertEqual(result.total_income, Decimal("250.00"))
        self.assertEqual(result.total_expense, Decimal("100.00"))
        self.assertEqual(result.balance, Decimal("150.00"))

    def test_today_rate_failure_sets_degradation_flag_and_shows_native_amounts(self):
        today = date.today()
        transaction = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            transaction_date=today,
        )

        with patch(
            "financetracker.services.display_conversion.get_rate",
            side_effect=CurrencyConversionError("network down"),
        ):
            result = convert_for_display(
                [transaction],
                "CZK",
                totals_transactions=[transaction],
            )

        row = result.rows[0]
        self.assertTrue(result.conversion_degraded)
        self.assertEqual(row.primary_amount, Decimal("10.00"))
        self.assertEqual(row.primary_currency, "EUR")
        self.assertFalse(row.show_native_footnote)
        self.assertIsNone(result.total_income)
        self.assertIsNone(result.total_expense)
        self.assertIsNone(result.balance)

    def test_historical_rate_failure_does_not_degrade_dashboard(self):
        past = date.today() - timedelta(days=7)
        converted_tx = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type="income",
            transaction_date=past,
            description="converted",
        )
        failed_tx = create_transaction(
            self.user,
            amount=Decimal("5.00"),
            currency="USD",
            type="expense",
            transaction_date=past - timedelta(days=1),
            description="failed",
        )

        def fake_get_rate(from_currency, to_currency, on_date=None):
            if from_currency == "USD":
                raise CurrencyConversionError("no historical rate")
            return Decimal("25.00")

        with patch(
            "financetracker.services.display_conversion.get_rate",
            side_effect=fake_get_rate,
        ):
            result = convert_for_display(
                [converted_tx, failed_tx],
                "CZK",
                totals_transactions=[converted_tx, failed_tx],
            )

        self.assertFalse(result.conversion_degraded)
        self.assertEqual(result.rows[0].primary_amount, Decimal("250.00"))
        self.assertEqual(result.rows[1].primary_amount, Decimal("5.00"))
        self.assertEqual(result.rows[1].primary_currency, "USD")
        self.assertEqual(result.total_income, Decimal("250.00"))
        self.assertEqual(result.total_expense, Decimal("0"))
        self.assertEqual(result.balance, Decimal("250.00"))
