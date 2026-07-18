"""Locale-aware display formatting for monetary amounts."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils import translation
from django.utils.formats import number_format
from django.utils.translation.trans_real import parse_accept_lang_header


def locale_from_accept_language(header: str | None) -> str:
    """Pick the best Django language code from an Accept-Language header."""
    if not header:
        return settings.LANGUAGE_CODE
    for language, _quality in parse_accept_lang_header(header):
        try:
            return translation.get_supported_language_variant(language)
        except LookupError:
            continue
    return settings.LANGUAGE_CODE


def format_amount(
    amount: Decimal | int | float | str,
    *,
    locale: str,
    decimal_places: int = 2,
) -> str:
    """Format a number with locale-aware grouping and decimal separator."""
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    with translation.override(locale):
        return number_format(
            value,
            decimal_pos=decimal_places,
            use_l10n=True,
            force_grouping=True,
        )


def format_money(
    amount: Decimal | int | float | str,
    currency: str,
    *,
    locale: str,
    decimal_places: int = 2,
) -> str:
    """Format an amount with a trailing ISO currency code."""
    return f"{format_amount(amount, locale=locale, decimal_places=decimal_places)} {currency.upper()}"
