from decimal import Decimal, InvalidOperation

from django import template
from django.utils.formats import number_format

register = template.Library()


def _to_decimal(value):
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value


def _coerce_int(value, default=2):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@register.filter
def br_currency(value, decimal_places=2):
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return ""
    if not isinstance(decimal_value, Decimal):
        return decimal_value

    places = _coerce_int(decimal_places, default=2)
    return number_format(
        decimal_value,
        decimal_pos=places,
        use_l10n=True,
        force_grouping=True,
    )


@register.filter
def br_decimal(value, decimal_places=2):
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return ""
    if not isinstance(decimal_value, Decimal):
        return decimal_value

    places = _coerce_int(decimal_places, default=2)
    return number_format(
        decimal_value,
        decimal_pos=places,
        use_l10n=True,
        force_grouping=False,
    )
