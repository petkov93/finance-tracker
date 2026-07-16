from datetime import date, timedelta
from decimal import Decimal
import requests
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from financetracker.models import ExchangeRate
from financetracker.services.currency import RateResult
from financetracker.services.display_conversion import convert_for_display
from financetracker.tests.factories import create_transaction, create_user


def _constant_get_rates(rate: Decimal, stale_date=None):
    def fake(keys):
        return {
            key: RateResult(rate=rate, stale_date=stale_date)
            for key in keys
        }

    return fake


def _mapped_get_rates(rate_by_key: dict):
    def fake(keys):
        return {
            key: RateResult(rate=rate_by_key[key])
            for key in keys
            if key in rate_by_key
        }

    return fake


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
        rates = {("EUR", "CZK", past): Decimal("25.00")}

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_mapped_get_rates(rates),
        ):
            result = convert_for_display([transaction], "CZK")

        row = result.rows[0]
        self.assertEqual(row.primary_amount, Decimal("250.00"))
        self.assertEqual(row.primary_currency, "CZK")
        self.assertEqual(row.native_amount, Decimal("10.00"))
        self.assertEqual(row.native_currency, "EUR")
        self.assertTrue(row.show_native_footnote)
        self.assertFalse(result.conversion_degraded)
        self.assertIsNone(result.rates_stale_date)

    @patch("financetracker.services.display_conversion.get_rates")
    def test_batches_unique_pair_date_rate_lookups(self, mock_get_rates):
        past = date.today() - timedelta(days=3)
        other_past = date.today() - timedelta(days=5)
        mock_get_rates.side_effect = _constant_get_rates(Decimal("25.00"))

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

        self.assertEqual(mock_get_rates.call_count, 1)
        requested = set(mock_get_rates.call_args.args[0])
        self.assertEqual(
            requested,
            {("EUR", "CZK", past), ("USD", "CZK", other_past)},
        )

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
        rates = {("EUR", "CZK", past): Decimal("25.00")}

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_mapped_get_rates(rates),
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
            "financetracker.services.display_conversion.get_rates",
            return_value={},
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
        self.assertIsNone(result.rates_stale_date)

    def test_stale_rates_compute_totals_and_set_stale_date(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        transaction = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            type="income",
            transaction_date=today,
        )

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_constant_get_rates(Decimal("25.00"), stale_date=yesterday),
        ):
            result = convert_for_display(
                [transaction],
                "CZK",
                totals_transactions=[transaction],
            )

        self.assertFalse(result.conversion_degraded)
        self.assertEqual(result.rates_stale_date, yesterday)
        self.assertEqual(result.total_income, Decimal("250.00"))
        self.assertEqual(result.total_expense, Decimal("0"))
        self.assertEqual(result.balance, Decimal("250.00"))
        row = result.rows[0]
        self.assertEqual(row.primary_amount, Decimal("250.00"))
        self.assertEqual(row.primary_currency, "CZK")
        self.assertTrue(row.show_native_footnote)

    def test_no_rate_at_all_sets_degraded_without_stale_date(self):
        today = date.today()
        transaction = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            transaction_date=today,
        )

        with patch(
            "financetracker.services.display_conversion.get_rates",
            return_value={},
        ):
            result = convert_for_display(
                [transaction],
                "CZK",
                totals_transactions=[transaction],
            )

        self.assertTrue(result.conversion_degraded)
        self.assertIsNone(result.rates_stale_date)
        self.assertIsNone(result.total_income)

    @patch("financetracker.services.currency.requests.get")
    def test_historical_snapshot_fetch_failure_does_not_crash_display(self, mock_get):
        past = date.today() - timedelta(days=7)
        mock_get.side_effect = requests.RequestException("network down")
        transaction = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            transaction_date=past,
        )

        result = convert_for_display([transaction], "CZK")

        self.assertFalse(result.conversion_degraded)
        row = result.rows[0]
        self.assertEqual(row.primary_amount, Decimal("10.00"))
        self.assertEqual(row.primary_currency, "EUR")
        self.assertFalse(row.show_native_footnote)

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

        rates = {("EUR", "CZK", past): Decimal("25.00")}

        with patch(
            "financetracker.services.display_conversion.get_rates",
            side_effect=_mapped_get_rates(rates),
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

    @patch("financetracker.services.currency.requests.get")
    def test_historical_transactions_group_snapshots_by_date(self, mock_get):
        past = date.today() - timedelta(days=3)
        other_past = date.today() - timedelta(days=5)

        def bulk_response(for_date: date):
            response = MagicMock()
            response.status_code = 200
            response.raise_for_status.return_value = None
            response.json.return_value = [
                {
                    "date": for_date.isoformat(),
                    "base": "EUR",
                    "quote": "USD",
                    "rate": 1.1,
                },
                {
                    "date": for_date.isoformat(),
                    "base": "EUR",
                    "quote": "CZK",
                    "rate": 25.0,
                },
            ]
            return response

        mock_get.side_effect = [bulk_response(past), bulk_response(other_past)]

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
                currency="USD",
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

        result = convert_for_display(
            transactions,
            "CZK",
            totals_transactions=transactions,
        )

        self.assertEqual(mock_get.call_count, 2)
        self.assertFalse(result.conversion_degraded)
        self.assertEqual(result.rows[0].primary_amount, Decimal("250.00"))
        self.assertEqual(
            result.rows[1].primary_amount,
            Decimal("20.00") * (Decimal("25.0") / Decimal("1.1")),
        )
        self.assertEqual(
            result.rows[2].primary_amount,
            Decimal("5.00") * (Decimal("25.0") / Decimal("1.1")),
        )
        self.assertEqual(result.total_income, Decimal("0"))
        self.assertEqual(
            result.total_expense,
            Decimal("250.00")
            + Decimal("20.00") * (Decimal("25.0") / Decimal("1.1"))
            + Decimal("5.00") * (Decimal("25.0") / Decimal("1.1")),
        )

    @patch("financetracker.services.currency.requests.get")
    def test_repeat_display_conversion_reuses_historical_db_without_http(self, mock_get):
        past = date.today() - timedelta(days=7)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {
                "date": past.isoformat(),
                "base": "EUR",
                "quote": "EUR",
                "rate": 1.0,
            },
            {
                "date": past.isoformat(),
                "base": "EUR",
                "quote": "CZK",
                "rate": 25.0,
            },
        ]
        mock_get.return_value = mock_response

        transaction = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            transaction_date=past,
        )

        convert_for_display([transaction], "CZK")
        mock_get.reset_mock()

        result = convert_for_display([transaction], "CZK")

        mock_get.assert_not_called()
        self.assertEqual(result.rows[0].primary_amount, Decimal("250.00"))
        self.assertFalse(result.conversion_degraded)

    def test_preloaded_historical_rates_used_without_http(self):
        past = date.today() - timedelta(days=7)
        fetched_at = timezone.now()
        ExchangeRate.objects.create(
            base_currency="EUR",
            quote_currency="CZK",
            rate_date=past,
            rate=Decimal("25.0"),
            fetched_at=fetched_at,
        )
        transaction = create_transaction(
            self.user,
            amount=Decimal("10.00"),
            currency="EUR",
            transaction_date=past,
        )

        with patch("financetracker.services.currency.requests.get") as mock_get:
            result = convert_for_display([transaction], "CZK")

        mock_get.assert_not_called()
        self.assertEqual(result.rows[0].primary_amount, Decimal("250.00"))

    def test_many_preloaded_dates_use_bounded_queries(self):
        """Default-currency switch must not do per-date rate round-trips."""
        from financetracker.models import SyncMetadata

        fetched_at = timezone.now()
        day_count = 40
        dates = [date.today() - timedelta(days=i + 1) for i in range(day_count)]
        for rate_date in dates:
            ExchangeRate.objects.create(
                base_currency="EUR",
                quote_currency="CZK",
                rate_date=rate_date,
                rate=Decimal("25.0"),
                fetched_at=fetched_at,
            )
        metadata = SyncMetadata.get_singleton()
        metadata.supported_currencies = {
            "EUR": "Euro",
            "CZK": "Czech Koruna",
        }
        metadata.save(update_fields=["supported_currencies"])

        transactions = [
            create_transaction(
                self.user,
                amount=Decimal("10.00"),
                currency="CZK",
                transaction_date=rate_date,
                description=f"tx-{rate_date.isoformat()}",
            )
            for rate_date in dates
        ]

        with patch("financetracker.services.currency.requests.get") as mock_get:
            with self.assertNumQueries(3):
                result = convert_for_display(transactions, "EUR")

        mock_get.assert_not_called()
        self.assertFalse(result.conversion_degraded)
        self.assertEqual(len(result.rows), day_count)
        self.assertEqual(result.rows[0].primary_currency, "EUR")
        self.assertEqual(
            result.rows[0].primary_amount,
            Decimal("10.00") / Decimal("25.0"),
        )
