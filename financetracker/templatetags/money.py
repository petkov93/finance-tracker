from django import template
from django.conf import settings

from financetracker.services.money_format import format_amount, format_money

register = template.Library()


def _locale_from_context(context) -> str:
    return context.get("display_locale") or settings.LANGUAGE_CODE


@register.simple_tag(takes_context=True)
def money(context, amount, currency, decimal_places=2):
    return format_money(
        amount,
        currency,
        locale=_locale_from_context(context),
        decimal_places=int(decimal_places),
    )


@register.simple_tag(takes_context=True)
def money_amount(context, amount, decimal_places=2):
    return format_amount(
        amount,
        locale=_locale_from_context(context),
        decimal_places=int(decimal_places),
    )
