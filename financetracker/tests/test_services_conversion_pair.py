from django.test import SimpleTestCase

from financetracker.services.conversion_pair import (
    DEFAULT_PAIR,
    ConversionPair,
    remember_conversion_pair,
    resolve_conversion_pair,
)

SUPPORTED = {"CZK", "EUR", "BGN", "USD"}


class ResolveConversionPairTests(SimpleTestCase):
    def test_empty_session_uses_default_pair(self):
        pair = resolve_conversion_pair({}, SUPPORTED)

        self.assertEqual(pair, DEFAULT_PAIR)
        self.assertEqual(pair, ConversionPair("CZK", "EUR"))

    def test_last_used_pair_overrides_default(self):
        session = {}
        remember_conversion_pair(session, ConversionPair("EUR", "BGN"))

        pair = resolve_conversion_pair(session, SUPPORTED)

        self.assertEqual(pair, ConversionPair("EUR", "BGN"))

    def test_url_overrides_last_used_pair(self):
        session = {}
        remember_conversion_pair(session, ConversionPair("EUR", "BGN"))

        pair = resolve_conversion_pair(
            session,
            SUPPORTED,
            url_from="USD",
            url_to="EUR",
        )

        self.assertEqual(pair, ConversionPair("USD", "EUR"))

    def test_sides_resolve_independently(self):
        session = {}
        remember_conversion_pair(session, ConversionPair("EUR", "BGN"))

        pair = resolve_conversion_pair(
            session,
            SUPPORTED,
            url_from="USD",
            url_to=None,
        )

        self.assertEqual(pair, ConversionPair("USD", "BGN"))

    def test_unsupported_url_falls_through_to_last_used_then_default(self):
        session = {}
        remember_conversion_pair(session, ConversionPair("EUR", "BGN"))

        pair = resolve_conversion_pair(
            session,
            SUPPORTED,
            url_from="FAKE",
            url_to="FAKE",
        )

        self.assertEqual(pair, ConversionPair("EUR", "BGN"))

        pair = resolve_conversion_pair(
            {},
            SUPPORTED,
            url_from="FAKE",
            url_to="NOPE",
        )

        self.assertEqual(pair, DEFAULT_PAIR)

    def test_unsupported_last_used_falls_through_to_default_side(self):
        session = {}
        remember_conversion_pair(session, ConversionPair("XXX", "YYY"))

        pair = resolve_conversion_pair(session, SUPPORTED)

        self.assertEqual(pair, DEFAULT_PAIR)

    def test_url_codes_are_normalized_to_uppercase(self):
        pair = resolve_conversion_pair(
            {},
            SUPPORTED,
            url_from="usd",
            url_to="eur",
        )

        self.assertEqual(pair, ConversionPair("USD", "EUR"))

    def test_resolve_does_not_mutate_session(self):
        session = {}

        resolve_conversion_pair(
            session,
            SUPPORTED,
            url_from="USD",
            url_to="EUR",
        )

        self.assertEqual(session, {})


class RememberConversionPairTests(SimpleTestCase):
    def test_remember_makes_pair_retrievable_as_last_used(self):
        session = {}

        remember_conversion_pair(session, ConversionPair("USD", "CZK"))

        self.assertEqual(
            resolve_conversion_pair(session, SUPPORTED),
            ConversionPair("USD", "CZK"),
        )

    def test_remember_overwrites_previous_last_used(self):
        session = {}
        remember_conversion_pair(session, ConversionPair("EUR", "BGN"))

        remember_conversion_pair(session, ConversionPair("USD", "CZK"))

        self.assertEqual(
            resolve_conversion_pair(session, SUPPORTED),
            ConversionPair("USD", "CZK"),
        )
