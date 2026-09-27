from django import template

register = template.Library()


@register.filter
def comma(value):
    """1234567 -> "1,234,567" (Korean pages use comma grouping regardless of locale)."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value
