"""Fixed-window per-key request limits backed by Django's cache.

Use a shared cache (CACHE_URL=redis://...) when running more than one process;
the default in-memory cache counts per process.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache


def hit(bucket: str, key: str | int) -> bool:
    """Count one request; False once the limit for this window is used up."""
    limit, window = settings.RATE_LIMITS[bucket]
    slot = int(time.time() // window)
    cache_key = f"rl:{bucket}:{key}:{slot}"
    cache.add(cache_key, 0, window + 5)
    try:
        count = cache.incr(cache_key)
    except ValueError:  # expired between add and incr
        cache.set(cache_key, 1, window + 5)
        count = 1
    return count <= limit


def client_ip(request) -> str:
    # Behind a proxy, configure it to set X-Forwarded-For and trust only that hop.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") if settings.TRUST_X_FORWARDED_FOR else ""
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
