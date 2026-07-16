from collections.abc import Collection, MutableMapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConversionPair:
    from_currency: str
    to_currency: str


DEFAULT_PAIR = ConversionPair("CZK", "EUR")

_SESSION_FROM_KEY = "converter_from_currency"
_SESSION_TO_KEY = "converter_to_currency"


def resolve_conversion_pair(
    session: MutableMapping[str, Any],
    supported: Collection[str],
    *,
    url_from: str | None = None,
    url_to: str | None = None,
) -> ConversionPair:
    from_currency = _resolve_currency(
        url_from,
        supported,
        session.get(_SESSION_FROM_KEY),
        DEFAULT_PAIR.from_currency,
    )
    to_currency = _resolve_currency(
        url_to,
        supported,
        session.get(_SESSION_TO_KEY),
        DEFAULT_PAIR.to_currency,
    )
    return ConversionPair(from_currency, to_currency)


def remember_conversion_pair(
    session: MutableMapping[str, Any],
    pair: ConversionPair,
) -> None:
    session[_SESSION_FROM_KEY] = pair.from_currency
    session[_SESSION_TO_KEY] = pair.to_currency


def _resolve_currency(
    code: str | None,
    supported: Collection[str],
    session_value: Any,
    default: str,
) -> str:
    if code:
        normalized = code.upper()
        if normalized in supported:
            return normalized
    if session_value and session_value in supported:
        return session_value
    return default
