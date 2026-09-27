"""Keyword and market research built on Naver's official APIs.

Every function returns plain JSON-able dicts: they back both the web UI and
the agent's tools.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from datetime import date, timedelta
from typing import Callable

from django.conf import settings
from django.utils import timezone

from pivend.naver.openapi import NaverOpenAPIClient, resolve_category
from pivend.naver.searchad import MAX_HINT_KEYWORDS, KeywordToolRow, SearchAdClient

from .models import ApiCache, KeywordStat
from .text import normalize_keyword, token_frequencies

MAX_KEYWORDS_PER_LOOKUP = 20
MAX_TREND_KEYWORDS = 5


# Client factories — tests replace these.
def searchad_client() -> SearchAdClient:
    return SearchAdClient()


def openapi_client() -> NaverOpenAPIClient:
    return NaverOpenAPIClient()


def _cutoff():
    return timezone.now() - timedelta(hours=settings.RESEARCH_CACHE_HOURS)


def _cache_key(raw: str) -> str:
    return raw if len(raw) <= 200 else hashlib.sha256(raw.encode()).hexdigest()


def cached(kind: str, raw_key: str, fetch: Callable[[], dict | list]) -> dict | list:
    key = _cache_key(raw_key)
    entry = ApiCache.objects.filter(kind=kind, key=key, fetched_at__gte=_cutoff()).first()
    if entry is not None:
        return entry.payload
    payload = fetch()
    ApiCache.objects.update_or_create(kind=kind, key=key, defaults={"payload": payload})
    return payload


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        item = item.strip()
        norm = normalize_keyword(item)
        if item and norm not in seen:
            seen.add(norm)
            out.append(item)
    return out


def _upsert_rows(rows: list[KeywordToolRow]) -> None:
    now = timezone.now()
    objs = {}
    for row in rows:
        norm = normalize_keyword(row.keyword)
        if not norm:
            continue
        objs[norm] = KeywordStat(
            normalized=norm,
            keyword=row.keyword,
            pc_searches=row.pc_searches,
            mobile_searches=row.mobile_searches,
            pc_under_10=row.pc_under_10,
            mobile_under_10=row.mobile_under_10,
            pc_clicks=row.pc_clicks,
            mobile_clicks=row.mobile_clicks,
            pc_ctr=row.pc_ctr,
            mobile_ctr=row.mobile_ctr,
            competition=row.competition,
            ad_depth=row.ad_depth,
            fetched_at=now,
        )
    if not objs:
        return
    update_fields = [
        "keyword", "pc_searches", "mobile_searches", "pc_under_10", "mobile_under_10",
        "pc_clicks", "mobile_clicks", "pc_ctr", "mobile_ctr", "competition", "ad_depth",
        "fetched_at",
    ]
    KeywordStat.objects.bulk_create(
        list(objs.values()),
        update_conflicts=True,
        unique_fields=["normalized"],
        update_fields=update_fields,
        batch_size=500,
    )


def _fetch_keywordstool(hints: list[str]) -> list[str]:
    """Call the keyword tool and upsert everything it returns.

    Returns the normalized keywords in the order the API listed them.
    """
    rows = searchad_client().keywordstool(hints)
    _upsert_rows(rows)
    return [normalize_keyword(r.keyword) for r in rows]


def shopping_total(query: str) -> int:
    """Number of listings Naver Shopping returns for a query."""
    payload = cached(
        "shop_total",
        query,
        lambda: {"total": openapi_client().shopping_search(query, display=1).total},
    )
    return int(payload["total"])


def get_keyword_stats(keywords: list[str], with_competition: bool = False) -> dict:
    keywords = _dedupe(keywords)[:MAX_KEYWORDS_PER_LOOKUP]
    norms = {k: normalize_keyword(k) for k in keywords}

    fresh = set(
        KeywordStat.objects.filter(normalized__in=norms.values(), fetched_at__gte=_cutoff())
        .values_list("normalized", flat=True)
    )
    missing = [k for k in keywords if norms[k] not in fresh]
    for i in range(0, len(missing), MAX_HINT_KEYWORDS):
        _fetch_keywordstool(missing[i : i + MAX_HINT_KEYWORDS])

    stats = {s.normalized: s for s in KeywordStat.objects.filter(normalized__in=norms.values())}
    results = []
    for keyword in keywords:
        stat = stats.get(norms[keyword])
        if stat is None:
            results.append({"query": keyword, "found": False})
            continue
        row = {"query": keyword, "found": True, **stat.as_dict()}
        if with_competition:
            products = shopping_total(keyword)
            row["product_count"] = products
            # Listings per monthly search: lower means less crowded (경쟁강도).
            row["competition_ratio"] = round(products / max(stat.total_searches, 1), 2)
        results.append(row)
    return {
        "source": "Naver 검색광고 키워드도구 (monthly searches, last 30 days)",
        "keywords": results,
    }


def get_related_keywords(seed: str, limit: int = 50, min_searches: int = 0) -> dict:
    seed = seed.strip()
    related = cached("kwtool", normalize_keyword(seed), lambda: _fetch_keywordstool([seed]))
    stats = {s.normalized: s for s in KeywordStat.objects.filter(normalized__in=related)}
    rows = [stats[n] for n in related if n in stats]
    rows = [s for s in rows if s.total_searches >= min_searches]
    rows.sort(key=lambda s: s.total_searches, reverse=True)
    seed_norm = normalize_keyword(seed)
    return {
        "seed": seed,
        "source": "Naver 검색광고 키워드도구",
        "count": len(rows),
        "keywords": [
            {
                "keyword": s.keyword,
                "total": s.total_searches,
                "pc": s.pc_searches,
                "mobile": s.mobile_searches,
                "ad_competition": s.competition,
                "contains_seed": seed_norm in s.normalized,
            }
            for s in rows[: max(1, min(limit, 200))]
        ],
    }


def _summarize_series(points: list[dict]) -> dict:
    ratios = [p["ratio"] for p in points]
    if not ratios:
        return {}
    peak = max(points, key=lambda p: p["ratio"])
    low = min(points, key=lambda p: p["ratio"])
    summary = {
        "mean": round(statistics.fmean(ratios), 1),
        "last": round(ratios[-1], 1),
        "peak_period": peak["period"],
        "low_period": low["period"],
    }
    if len(ratios) >= 6:
        recent = statistics.fmean(ratios[-3:])
        before = statistics.fmean(ratios[-6:-3])
        if before > 0:
            summary["recent_change_pct"] = round((recent / before - 1) * 100, 1)
    return summary


def get_keyword_trend(
    keywords: list[str],
    months: int = 12,
    time_unit: str = "month",
    category: str | None = None,
    device: str | None = None,
    gender: str | None = None,
    ages: list[str] | None = None,
) -> dict:
    keywords = _dedupe(keywords)[:MAX_TREND_KEYWORDS]
    if not keywords:
        raise ValueError("At least one keyword is required")
    if time_unit not in {"date", "week", "month"}:
        raise ValueError("time_unit must be date, week or month")
    months = max(1, min(months, 60))
    end = date.today() - timedelta(days=1)
    start = (end.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)

    request = {
        "keywords": keywords, "start": start.isoformat(), "end": end.isoformat(),
        "time_unit": time_unit, "category": category, "device": device,
        "gender": gender, "ages": ages,
    }
    raw_key = json.dumps(request, ensure_ascii=False, sort_keys=True)

    def fetch():
        client = openapi_client()
        if category:
            return client.shopping_keyword_trend(
                category, keywords, start.isoformat(), end.isoformat(), time_unit,
                device=device, gender=gender, ages=ages,
            )
        return client.search_trend(
            {k: [k] for k in keywords}, start.isoformat(), end.isoformat(), time_unit,
            device=device, gender=gender, ages=ages,
        )

    data = cached("trend", raw_key, fetch)
    series = []
    for result in data.get("results", []):
        points = [{"period": p["period"], "ratio": p["ratio"]} for p in result.get("data", [])]
        series.append({"keyword": result.get("title"), "summary": _summarize_series(points), "points": points})
    return {
        "source": (
            f"Naver 데이터랩 쇼핑인사이트 (category {resolve_category(category)}, click ratio)"
            if category
            else "Naver 데이터랩 검색어 트렌드 (search ratio)"
        ),
        "note": "Ratios are relative: 100 is the highest point across all keywords in this request.",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "time_unit": time_unit,
        "series": series,
    }


def _quantiles(values: list[int]) -> dict:
    if not values:
        return {}
    values = sorted(values)
    q = statistics.quantiles(values, n=4) if len(values) >= 2 else [values[0]] * 3
    return {
        "min": values[0],
        "p25": round(q[0]),
        "median": round(statistics.median(values)),
        "p75": round(q[2]),
        "max": values[-1],
    }


def analyze_competitors(query: str, sample: int = 40) -> dict:
    sample = max(1, min(sample, 100))
    payload = cached(
        "shop",
        f"{query}|{sample}",
        lambda: (lambda r: {"total": r.total, "items": [i.as_dict() for i in r.items]})(
            openapi_client().shopping_search(query, display=sample)
        ),
    )
    items = payload["items"]
    titles = [i["title"] for i in items]
    lengths = [len(t) for t in titles]
    return {
        "query": query,
        "source": "Naver 쇼핑 검색 API, 정확도(sim) order — not the personalized ranking shoppers see",
        "total_listings": payload["total"],
        "sampled": len(items),
        "price": _quantiles([i["lprice"] for i in items if i["lprice"] > 0]),
        "title_length": {
            "mean": round(statistics.fmean(lengths), 1) if lengths else 0,
            "min": min(lengths, default=0),
            "max": max(lengths, default=0),
        },
        "top_tokens": token_frequencies(titles),
        "top_malls": [{"name": n, "count": c} for n, c in Counter(i["mall_name"] for i in items if i["mall_name"]).most_common(10)],
        "top_brands": [{"name": n, "count": c} for n, c in Counter(i["brand"] for i in items if i["brand"]).most_common(10)],
        "categories": [
            {"path": p, "count": c}
            for p, c in Counter(" > ".join(i["categories"]) for i in items if i["categories"]).most_common(5)
        ],
        "top_listings": [
            {
                "rank": n + 1,
                "title": i["title"],
                "price": i["lprice"],
                "mall": i["mall_name"],
                "brand": i["brand"],
                "category": " > ".join(i["categories"]),
            }
            for n, i in enumerate(items[:10])
        ],
    }
