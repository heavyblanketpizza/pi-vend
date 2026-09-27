"""UI helpers: icons from the Lucide sprite, the brand mark, Korean number/time formatting."""

import itertools
from datetime import datetime

from django import template
from django.templatetags.static import static
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()
_mark_ids = itertools.count(1)


@register.simple_tag
def icon(name: str, cls: str = "", label: str = ""):
    aria = format_html('role="img" aria-label="{}"', label) if label else mark_safe('aria-hidden="true"')
    return format_html(
        '<svg class="i {}" {}><use href="{}#i-{}"></use></svg>',
        cls, aria, static("web/icons.svg"), name,
    )


@register.simple_tag
def brand_mark(cls: str = "brand-mark"):
    gid = f"bm{next(_mark_ids)}"
    return format_html(
        '<svg class="{cls}" viewBox="0 0 28 28" aria-hidden="true">'
        '<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#8A8AF6"/><stop offset="1" stop-color="#4B4BC8"/></linearGradient></defs>'
        '<rect width="28" height="28" rx="8" fill="url(#{gid})"/>'
        '<g fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round">'
        '<path d="M8.4 10.2h11.2"/><path d="M11.6 10.2v8.6"/><path d="M16.6 10.2v6.4c0 1.4.8 2.2 2.1 2.2h.5"/>'
        "</g></svg>",
        cls=cls, gid=gid,
    )


@register.filter
def comma(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value


@register.filter
def compact(value):
    """12345 -> 1.2만, 123456789 -> 1.2억 (Korean units)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    if abs(n) >= 100_000_000:
        return f"{n / 100_000_000:.1f}".rstrip("0").rstrip(".") + "억"
    if abs(n) >= 1_000_000:
        return f"{n / 10_000:,.0f}만"
    if abs(n) >= 10_000:
        return f"{n / 10_000:.1f}".rstrip("0").rstrip(".") + "만"
    return f"{n:,}"


@register.filter
def reltime(value):
    if not isinstance(value, datetime):
        return value
    now = timezone.now()
    seconds = (now - value).total_seconds()
    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{int(seconds // 60)}분 전"
    local, today = timezone.localtime(value), timezone.localtime(now)
    days = (today.date() - local.date()).days
    if days == 0:
        return f"{int(seconds // 3600)}시간 전"
    if days == 1:
        return "어제"
    if days < 7:
        return f"{days}일 전"
    if local.year == today.year:
        return f"{local.month}월 {local.day}일"
    return f"{local.year}. {local.month}. {local.day}."


@register.filter
def pct(value, total):
    try:
        return max(0.0, min(100.0, float(value) / float(total) * 100)) if float(total) else 0.0
    except (TypeError, ValueError):
        return 0.0


@register.filter
def month_label(period: str):
    """"2025-07-01" -> "2025년 7월"."""
    try:
        year, month = str(period)[:7].split("-")
        return f"{year}년 {int(month)}월"
    except ValueError:
        return period
