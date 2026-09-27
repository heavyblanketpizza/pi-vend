"""Dashboard aggregations over the seller's store data plus cached market data.

Nothing here calls an external API: market numbers come from the research
cache (KeywordStat), so the dashboard renders instantly and never burns quota.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Max, Q, Sum

from pivend.listings.models import ListingDraft
from pivend.research.models import KeywordStat
from pivend.research.services import scope_for
from pivend.research.text import normalize_keyword

from .models import AdDaily, DailySales, DailyTraffic, KeywordInflow, Store

PERIODS = (7, 30, 90)
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _pct(now: float, before: float) -> float | None:
    return round((now - before) / before * 100, 1) if before else None


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _sales_by_day(stores, start: date, end: date, product_ids=None) -> dict:
    """{(store_id, product_id, date): (orders, units, revenue)} with store totals resolved.

    A store/day with product rows uses their sum; otherwise its store-level row.
    """
    rows = DailySales.objects.filter(store__in=stores, date__range=(start, end))
    if product_ids is not None:
        rows = rows.filter(product_id__in=product_ids)
    return {(r.store_id, r.product_id, r.date): (r.orders, r.units, r.revenue) for r in rows}


def _store_totals(sales: dict) -> dict[tuple[int, date], tuple[int, int, int]]:
    product_level: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    store_level: dict[tuple, tuple] = {}
    for (store_id, product_id, day), values in sales.items():
        if product_id is None:
            store_level[(store_id, day)] = values
        else:
            acc = product_level[(store_id, day)]
            for i in range(3):
                acc[i] += values[i]
    totals = {k: tuple(v) for k, v in product_level.items()}
    for key, values in store_level.items():
        totals.setdefault(key, values)
    return totals


def data_range(owner) -> tuple[date, date] | None:
    stores = Store.objects.filter(owner=owner)
    last = DailySales.objects.filter(store__in=stores).aggregate(m=Max("date"))["m"]
    if last is None:
        return None
    first = DailySales.objects.filter(store__in=stores).order_by("date").values_list("date", flat=True).first()
    return first, last


def dashboard(owner, days: int = 30, store_id: int | None = None) -> dict | None:
    days = days if days in PERIODS else 30
    stores = Store.objects.filter(owner=owner)
    if store_id:
        stores = stores.filter(id=store_id)
    stores = list(stores)
    span = data_range(owner)
    if not stores or span is None:
        return None
    end = span[1]
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    marketplace = {s.id: s.marketplace for s in stores}

    sales = _sales_by_day(stores, prev_start, end)
    totals = _store_totals(sales)
    cur_days, prev_days = _days(start, end), _days(prev_start, prev_end)

    def daily(metric: int, day_list):
        by_day = defaultdict(int)
        for (store_id_, day), values in totals.items():
            by_day[day] += values[metric]
        return [by_day.get(d, 0) for d in day_list]

    revenue, revenue_prev = daily(2, cur_days), daily(2, prev_days)
    orders, orders_prev = daily(0, cur_days), daily(0, prev_days)
    units = sum(daily(1, cur_days))

    visits = [0] * len(cur_days)
    visits_prev = [0] * len(prev_days)
    for t in DailyTraffic.objects.filter(store__in=stores, date__range=(prev_start, end)).values("date").annotate(v=Sum("visits")):
        if t["date"] >= start:
            visits[(t["date"] - start).days] = t["v"]
        else:
            visits_prev[(t["date"] - prev_start).days] = t["v"]

    ads = AdDaily.objects.filter(store__in=stores)
    ad_now = ads.filter(date__range=(start, end)).aggregate(spend=Sum("spend"), revenue=Sum("revenue"), clicks=Sum("clicks"))
    ad_prev = ads.filter(date__range=(prev_start, prev_end)).aggregate(spend=Sum("spend"), revenue=Sum("revenue"))

    rev, rev_p = sum(revenue), sum(revenue_prev)
    ords, ords_p = sum(orders), sum(orders_prev)
    kpis = [
        _kpi("revenue", "매출", rev, rev_p, revenue, unit="원"),
        _kpi("orders", "주문", ords, ords_p, orders, unit="건"),
        _kpi(
            "aov", "객단가", round(rev / ords) if ords else 0, round(rev_p / ords_p) if ords_p else 0,
            [round(r / o) if o else 0 for r, o in zip(revenue, orders)], unit="원",
        ),
    ]
    if sum(visits):
        conv = ords / sum(visits) * 100
        conv_p = ords_p / sum(visits_prev) * 100 if sum(visits_prev) else 0
        kpis.append(
            _kpi(
                "conversion", "구매 전환율", round(conv, 2), round(conv_p, 2),
                [round(o / v * 100, 2) if v else 0 for o, v in zip(orders, visits)], unit="%", points=True,
            )
        )
    if ad_now["spend"]:
        roas = (ad_now["revenue"] or 0) / ad_now["spend"] * 100
        roas_p = (ad_prev["revenue"] or 0) / ad_prev["spend"] * 100 if ad_prev["spend"] else 0
        kpis.append(_kpi("roas", "광고 ROAS", round(roas), round(roas_p), None, unit="%", points=True))

    return {
        "period": {"days": days, "start": start, "end": end, "prev_start": prev_start, "prev_end": prev_end},
        "stores": stores,
        "is_demo": all(s.source == Store.Source.DEMO for s in stores),
        "kpis": kpis,
        "daily": {"days": cur_days, "revenue": revenue, "revenue_prev": revenue_prev, "orders": orders, "visits": visits},
        "channels": _channels(totals, marketplace, start),
        "products": _products(sales, start, end, prev_start, cur_days),
        "weekday": _weekday(revenue, cur_days),
        "keywords": _keywords(owner, stores, start, end, days),
        "ads": _ads(stores, start, end, ad_now),
        "market": _market(owner, stores, start, end),
        "units": units,
    }


def _kpi(key, label, value, prev, series, unit="", points=False) -> dict:
    delta = round(value - prev, 2) if points else _pct(value, prev)
    return {
        "key": key, "label": label, "value": value, "prev": prev, "unit": unit,
        "delta": delta, "delta_points": points, "series": series,
    }


def _channels(totals, marketplace, start) -> list[dict]:
    by_channel = defaultdict(int)
    for (store_id, day), values in totals.items():
        if day >= start:
            by_channel[marketplace[store_id]] += values[2]
    total = sum(by_channel.values()) or 1
    labels = {"naver": "네이버 스마트스토어", "coupang": "쿠팡"}
    order = ["naver", "coupang"]
    return [
        {"key": k, "label": labels.get(k, k), "revenue": by_channel[k], "share": round(by_channel[k] / total * 100, 1)}
        for k in sorted(by_channel, key=lambda k: order.index(k) if k in order else 9)
    ]


def _products(sales, start, end, prev_start, cur_days) -> list[dict]:
    from .models import Product

    now = defaultdict(lambda: [0, 0, 0])
    before = defaultdict(int)
    series = defaultdict(lambda: defaultdict(int))
    for (store_id, product_id, day), (o, u, r) in sales.items():
        if product_id is None:
            continue
        if day >= start:
            acc = now[product_id]
            acc[0] += o
            acc[1] += u
            acc[2] += r
            series[product_id][day] += r
        else:
            before[product_id] += r
    if not now:
        return []
    names = {p.id: p for p in Product.objects.filter(id__in=now).select_related("store")}
    total = sum(v[2] for v in now.values()) or 1
    top = sorted(now.items(), key=lambda kv: kv[1][2], reverse=True)[:8]
    peak = max(v[2] for _, v in top) or 1
    return [
        {
            "id": pid,
            "name": names[pid].name,
            "marketplace": names[pid].store.marketplace,
            "orders": o, "units": u, "revenue": r,
            "share": round(r / total * 100, 1),
            "bar": round(r / peak * 100, 1),
            "delta": _pct(r, before.get(pid, 0)),
            "series": [series[pid].get(d, 0) for d in cur_days],
        }
        for pid, (o, u, r) in top
    ]


def _weekday(revenue: list[int], days: list[date]) -> list[dict]:
    sums, counts = [0] * 7, [0] * 7
    for value, day in zip(revenue, days):
        sums[day.weekday()] += value
        counts[day.weekday()] += 1
    avgs = [round(s / c) if c else 0 for s, c in zip(sums, counts)]
    overall = sum(avgs) / 7 if any(avgs) else 0
    return [
        {"label": WEEKDAYS[i], "value": avgs[i], "vs_avg": _pct(avgs[i], overall)}
        for i in range(7)
    ]


def _keywords(owner, stores, start, end, days) -> list[dict]:
    rows = (
        KeywordInflow.objects.filter(store__in=stores, date__range=(start, end))
        .values("keyword")
        .annotate(visits=Sum("visits"), orders=Sum("orders"), revenue=Sum("revenue"))
        .order_by("-visits")[:15]
    )
    rows = list(rows)
    stats = {
        s.normalized: s for s in KeywordStat.objects.filter(
            scope=scope_for(owner), normalized__in=[normalize_keyword(r["keyword"]) for r in rows]
        )
    }
    peak = max((r["visits"] for r in rows), default=0) or 1
    out = []
    for r in rows:
        stat = stats.get(normalize_keyword(r["keyword"]))
        market = stat.total_searches if stat else None
        # Share of the keyword's search demand in this period that reached the store.
        capture = round(r["visits"] / (market * days / 30) * 100, 1) if market else None
        out.append({
            "keyword": r["keyword"], "visits": r["visits"], "orders": r["orders"], "revenue": r["revenue"],
            "conversion": round(r["orders"] / r["visits"] * 100, 1) if r["visits"] else 0,
            "market": market, "capture": capture, "bar": round(r["visits"] / peak * 100, 1),
            "competition": stat.competition if stat else "",
        })
    return out


def _ads(stores, start, end, totals) -> dict | None:
    if not totals["spend"]:
        return None
    rows = (
        AdDaily.objects.filter(store__in=stores, date__range=(start, end))
        .exclude(keyword="")
        .values("keyword")
        .annotate(spend=Sum("spend"), revenue=Sum("revenue"), clicks=Sum("clicks"), conversions=Sum("conversions"))
        .order_by("-spend")[:10]
    )
    keywords = [
        {**r, "roas": round(r["revenue"] / r["spend"] * 100) if r["spend"] else 0,
         "cpc": round(r["spend"] / r["clicks"]) if r["clicks"] else 0}
        for r in rows
    ]
    spend, revenue = totals["spend"], totals["revenue"] or 0
    return {"spend": spend, "revenue": revenue, "roas": round(revenue / spend * 100), "clicks": totals["clicks"] or 0, "keywords": keywords}


def _market(owner, stores, start, end) -> list[dict]:
    """Keywords the seller cares about (draft targets + top inflows) with market demand from the cache."""
    tracked: list[str] = []
    for keywords in ListingDraft.objects.filter(owner=owner).values_list("target_keywords", flat=True):
        tracked.extend(keywords or [])
    tracked.extend(
        KeywordInflow.objects.filter(store__in=stores, date__range=(start, end))
        .values("keyword").annotate(v=Sum("visits")).order_by("-v").values_list("keyword", flat=True)[:6]
    )
    seen, ordered = set(), []
    for k in tracked:
        n = normalize_keyword(k)
        if n and n not in seen:
            seen.add(n)
            ordered.append((k, n))
    stats = {s.normalized: s for s in KeywordStat.objects.filter(scope=scope_for(owner), normalized__in=[n for _, n in ordered])}
    rows = [
        {"keyword": k, "volume": stats[n].total_searches, "mobile_share": round(stats[n].mobile_searches / stats[n].total_searches * 100) if stats[n].total_searches else 0,
         "competition": stats[n].competition, "fetched_at": stats[n].fetched_at}
        for k, n in ordered if n in stats
    ]
    rows.sort(key=lambda r: r["volume"], reverse=True)
    peak = max((r["volume"] for r in rows), default=0) or 1
    for r in rows:
        r["bar"] = round(r["volume"] / peak * 100, 1)
    return rows[:8]


def overview_for_agent(owner, days: int = 30) -> dict:
    """Compact JSON for the agent's store_overview tool."""
    from .insights import build_insights

    data = dashboard(owner, days)
    if data is None:
        return {"has_data": False, "message": "아직 스토어 데이터가 없어요. 데이터 연결 페이지에서 리포트를 업로드하세요."}
    p = data["period"]
    return {
        "has_data": True,
        "demo": data["is_demo"],
        "period": {"start": p["start"].isoformat(), "end": p["end"].isoformat(), "days": p["days"],
                   "compared_with": f"{p['prev_start'].isoformat()}~{p['prev_end'].isoformat()}"},
        "kpis": {k["key"]: {"value": k["value"], "previous": k["prev"], "change": k["delta"], "unit": k["unit"],
                            "change_is_points": k["delta_points"]} for k in data["kpis"]},
        "channels": data["channels"],
        "top_products": [{k: p_[k] for k in ("name", "marketplace", "revenue", "orders", "share", "delta")} for p_ in data["products"]],
        "weekday_avg_revenue": {w["label"]: w["value"] for w in data["weekday"]},
        "inflow_keywords": [{k: r[k] for k in ("keyword", "visits", "orders", "conversion", "market", "capture")} for r in data["keywords"]],
        "ads": data["ads"],
        "insights": [{k: i[k] for k in ("level", "title", "body")} for i in build_insights(data)],
    }


def has_store_data(owner) -> bool:
    return DailySales.objects.filter(Q(store__owner=owner)).exists()
