from django import template
from decimal import Decimal

register = template.Library()


@register.filter
def cop(value):
    try:
        return "$ " + f"{Decimal(value):,.2f}".replace(",", "X").replace(
            ".", ","
        ).replace("X", ".")
    except Exception:
        return "$ 0,00"


@register.filter
def plain_number(value):
    """Sin ceros decimales sobrantes ni separadores ambiguos de miles."""
    try:
        result = format(Decimal(value), "f")
        if "." in result:
            result = result.rstrip("0").rstrip(".")
        return result.replace(".", ",")
    except (ValueError, TypeError):
        return str(value)
