from datetime import timedelta

import pytest
from django.utils import timezone

from pivend.naver.openapi import ShoppingItem, ShoppingSearchResult
from pivend.naver.searchad import KeywordToolRow
from pivend.research import services
from pivend.research.models import ApiCache, KeywordStat
from pivend.research.text import compound_parts, normalize_keyword, token_frequencies


def row(keyword, pc, mobile, comp="중간"):
    return KeywordToolRow(
        keyword=keyword, pc_searches=pc, mobile_searches=mobile, pc_under_10=False,
        mobile_under_10=False, pc_clicks=0, mobile_clicks=0, pc_ctr=0, mobile_ctr=0,
        competition=comp, ad_depth=0,
    )


class FakeSearchAd:
    def __init__(self):
        self.calls = []

    def keywordstool(self, hints):
        self.calls.append(list(hints))
        return [
            row("린넨원피스", 2000, 18000, "높음"),
            row("린넨원피스롱", 300, 2700, "중간"),
            row("여름원피스", 5000, 45000, "높음"),
            row("린넨셔츠원피스", 5, 40, "낮음"),
        ]


def item(title, price, mall="몰", brand="", cats=("패션의류", "여성의류", "원피스")):
    return ShoppingItem(
        title=title, link="", image="", lprice=price, hprice=0, mall_name=mall,
        product_id="1", product_type="1", brand=brand, maker="", categories=cats,
    )


class FakeOpenAPI:
    def __init__(self):
        self.searches = []
        self.trends = []

    def shopping_search(self, query, display=40, start=1, sort="sim"):
        self.searches.append((query, display))
        return ShoppingSearchResult(
            total=180000,
            items=[
                item("린넨 셔츠원피스 여름 롱", 29900, "스토어A", "브랜드X"),
                item("여름 린넨 원피스 빅사이즈", 35900, "스토어B"),
                item("린넨 원피스 루즈핏", 19900, "스토어A"),
            ][:display],
        )

    def search_trend(self, groups, start, end, unit, **kw):
        self.trends.append(("search", groups))
        data = [{"period": f"2026-{m:02d}-01", "ratio": r} for m, r in enumerate([10, 20, 60, 100, 80, 40], start=1)]
        return {"results": [{"title": name, "keywords": kws, "data": data} for name, kws in groups.items()]}

    def shopping_keyword_trend(self, category, keywords, start, end, unit, **kw):
        self.trends.append(("shopping", category))
        return {"results": [{"title": k, "keyword": [k], "data": [{"period": "2026-01-01", "ratio": 50}]} for k in keywords]}


@pytest.fixture
def fakes(monkeypatch):
    searchad, openapi = FakeSearchAd(), FakeOpenAPI()
    monkeypatch.setattr(services, "searchad_client", lambda: searchad)
    monkeypatch.setattr(services, "openapi_client", lambda: openapi)
    return searchad, openapi


def test_normalize_keyword():
    assert normalize_keyword(" 린넨 원피스 ") == "린넨원피스"
    assert normalize_keyword("nike 에어") == "NIKE에어"


@pytest.mark.django_db
def test_keyword_stats_fetches_once_and_caches(fakes):
    searchad, openapi = fakes
    result = services.get_keyword_stats(["린넨 원피스", "린넨원피스", "없는키워드"], with_competition=True)

    assert searchad.calls == [["린넨 원피스", "없는키워드"]]  # duplicates collapse
    first, missing = result["keywords"]
    assert first["found"] and first["monthly_searches"]["total"] == 20000
    assert first["product_count"] == 180000
    assert first["competition_ratio"] == 9.0
    assert missing == {"query": "없는키워드", "found": False}
    # Related keywords from the same call are cached too.
    assert KeywordStat.objects.filter(normalized="여름원피스").exists()

    services.get_keyword_stats(["여름 원피스"])
    assert len(searchad.calls) == 1


@pytest.mark.django_db
def test_stale_stats_are_refetched(fakes, settings):
    searchad, _ = fakes
    services.get_keyword_stats(["린넨원피스"])
    KeywordStat.objects.update(fetched_at=timezone.now() - timedelta(hours=settings.RESEARCH_CACHE_HOURS + 1))
    services.get_keyword_stats(["린넨원피스"])
    assert len(searchad.calls) == 2


@pytest.mark.django_db
def test_related_keywords_sorted_and_filtered(fakes):
    result = services.get_related_keywords("린넨 원피스", limit=10, min_searches=100)
    keywords = [k["keyword"] for k in result["keywords"]]
    assert keywords == ["여름원피스", "린넨원피스", "린넨원피스롱"]
    assert result["keywords"][1]["contains_seed"] is True
    assert result["keywords"][0]["contains_seed"] is False
    assert ApiCache.objects.filter(kind="kwtool").count() == 1


@pytest.mark.django_db
def test_keyword_trend_summary(fakes):
    _, openapi = fakes
    result = services.get_keyword_trend(["린넨 원피스"], months=6)
    series = result["series"][0]
    assert series["summary"]["peak_period"] == "2026-04-01"
    assert series["summary"]["low_period"] == "2026-01-01"
    assert series["summary"]["recent_change_pct"] == pytest.approx((220 / 3) / (90 / 3) * 100 - 100, abs=0.1)

    services.get_keyword_trend(["린넨 원피스"], category="패션의류")
    assert openapi.trends[-1] == ("shopping", "패션의류")
    with pytest.raises(ValueError):
        services.get_keyword_trend([])


@pytest.mark.django_db
def test_analyze_competitors(fakes):
    result = services.analyze_competitors("린넨 원피스", sample=3)
    assert result["total_listings"] == 180000
    assert result["price"]["median"] == 29900
    assert result["price"]["min"] == 19900
    tokens = {t["token"]: t["titles"] for t in result["top_tokens"]}
    assert tokens["린넨"] == 3
    assert tokens["원피스"] == 3  # counted once per title, including "셔츠원피스"
    assert result["top_malls"][0] == {"name": "스토어A", "count": 2}
    assert result["categories"][0]["path"] == "패션의류 > 여성의류 > 원피스"
    assert result["top_listings"][0]["rank"] == 1


def test_compound_parts_only_splits_clean_noun_compounds():
    assert compound_parts("셔츠원피스") == ("셔츠", "원피스")
    assert compound_parts("원피스") == ()
    assert compound_parts("abc") == ()


def test_token_frequencies_empty():
    assert token_frequencies([]) == []
