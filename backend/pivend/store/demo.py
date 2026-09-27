"""Realistic demo store data so the dashboard can be explored before real data is connected."""

import math
import random
from datetime import timedelta

from django.utils import timezone

from .models import AdDaily, DailySales, DailyTraffic, KeywordInflow, Product, Store

# name, price, base daily units, seasonal peak month (1-12, None = flat), store key
PRODUCTS = [
    ("프렌치 린넨 셔츠 원피스", 39_900, 11, 7, "naver"),
    ("린넨 와이드 팬츠", 32_900, 8, 7, "naver"),
    ("코튼 오버핏 셔츠", 29_900, 6, None, "naver"),
    ("여름 버킷햇", 15_900, 5, 6, "naver"),
    ("초경량 캠핑 릴렉스 체어", 49_000, 7, 10, "coupang"),
    ("무선 미니 가습기", 24_900, 4, 12, "coupang"),
]
KEYWORDS = {
    "naver": [("린넨원피스", 0.22), ("린넨셔츠원피스", 0.12), ("여름원피스", 0.09), ("린넨와이드팬츠", 0.10),
              ("하늘상점", 0.07), ("오버핏셔츠", 0.06), ("버킷햇", 0.05), ("린넨롱원피스", 0.04)],
    "coupang": [("캠핑의자", 0.30), ("경량의자", 0.14), ("릴렉스체어", 0.08), ("미니가습기", 0.18), ("무선가습기", 0.09)],
}
ADS = {  # keyword: (daily spend, roas)
    "naver": {"린넨원피스": (38_000, 3.8), "여름원피스": (26_000, 0.9), "린넨와이드팬츠": (14_000, 4.6)},
    "coupang": {"캠핑의자": (30_000, 5.2), "미니가습기": (12_000, 2.1)},
}


def seasonal(month: float, peak: int | None) -> float:
    if peak is None:
        return 1.0
    distance = min(abs(month - peak), 12 - abs(month - peak))
    return 0.35 + 0.95 * math.exp(-(distance**2) / 6)


def create_demo(owner, days: int = 120, seed: int = 42) -> dict:
    """Replace the owner's demo stores with freshly generated data. Returns row counts."""
    rng = random.Random(seed)
    Store.objects.filter(owner=owner, source=Store.Source.DEMO).delete()
    stores = {
        "naver": Store.objects.create(owner=owner, marketplace="naver", name="하늘상점", source=Store.Source.DEMO),
        "coupang": Store.objects.create(owner=owner, marketplace="coupang", name="하늘상점 쿠팡", source=Store.Source.DEMO),
    }
    products = [(Product.objects.create(store=stores[key], name=name), price, base, peak, key)
                for name, price, base, peak, key in PRODUCTS]
    end = timezone.localdate() - timedelta(days=1)
    weekday_factor = [0.92, 0.95, 0.97, 1.0, 1.08, 1.22, 1.12]
    sales, traffic, inflows, ads = [], [], [], []
    for offset in range(days):
        day = end - timedelta(days=days - 1 - offset)
        month = day.month + (day.day - 15) / 30
        growth = 1 + 0.25 * offset / days
        store_orders = {"naver": 0, "coupang": 0}
        for product, price, base, peak, key in products:
            expected = base * seasonal(month, peak) * weekday_factor[day.weekday()] * growth
            units = max(0, round(rng.gauss(expected, expected * 0.22)))
            orders = max(0, round(units * rng.uniform(0.82, 0.95)))
            discount = rng.choice([1, 1, 1, 0.9])
            sales.append(DailySales(store=product.store, product=product, date=day, orders=orders, units=units,
                                    revenue=round(units * price * discount)))
            store_orders[key] += orders
        for key, store in stores.items():
            conversion = rng.uniform(0.028, 0.036) if key == "naver" else rng.uniform(0.034, 0.045)
            if key == "naver" and offset > days - 21:
                conversion *= 0.86  # a recent conversion slump to surface in insights
            visits = round(store_orders[key] / conversion) if store_orders[key] else rng.randint(40, 90)
            traffic.append(DailyTraffic(store=store, date=day, visits=visits, page_views=round(visits * rng.uniform(2.1, 2.8))))
            for keyword, share in KEYWORDS[key]:
                kv = round(visits * share * rng.uniform(0.8, 1.2))
                ko = round(kv * conversion * rng.uniform(0.7, 1.3))
                inflows.append(KeywordInflow(store=store, date=day, keyword=keyword, visits=kv, orders=ko,
                                             revenue=ko * rng.choice([29_900, 32_900, 39_900, 49_000])))
            for keyword, (spend, roas) in ADS[key].items():
                s = round(spend * rng.uniform(0.8, 1.2))
                clicks = round(s / rng.uniform(380, 620))
                revenue = round(s * roas * rng.uniform(0.75, 1.25))
                ads.append(AdDaily(store=store, date=day, keyword=keyword, impressions=clicks * rng.randint(28, 45),
                                   clicks=clicks, spend=s, conversions=round(revenue / 38_000), revenue=revenue))
    DailySales.objects.bulk_create(sales)
    DailyTraffic.objects.bulk_create(traffic)
    KeywordInflow.objects.bulk_create(inflows)
    AdDaily.objects.bulk_create(ads)
    return {"sales": len(sales), "keywords": len(inflows), "ads": len(ads), "end": end}
