import io
import json
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User

from pivend.research.models import KeywordStat
from pivend.store.analytics import dashboard, overview_for_agent
from pivend.store.demo import create_demo
from pivend.store.importers import ImportError_, detect_kind, import_report, match_columns, parse_date, parse_number
from pivend.store.insights import build_insights
from pivend.store.models import AdDaily, DailySales, DataImport, KeywordInflow, Product, Store
from pivend.web.charts import column_chart, line_chart, nice_ticks, won_short


@pytest.fixture
def owner(db):
    return User.objects.create_user("seller", password="pw")


@pytest.fixture
def store(owner):
    return Store.objects.create(owner=owner, marketplace="naver", name="하늘상점")


# ------------------------------------------------------------------ importer
def test_match_columns_prefers_exact_synonyms():
    cols = match_columns(["일자", "상품명", "결제수", "결제상품수량", "결제금액(원)"])
    assert cols == {"date": 0, "product": 1, "orders": 2, "units": 3, "revenue": 4}
    ads = match_columns(["날짜", "키워드", "노출수", "클릭수", "총비용(VAT포함)", "전환매출", "전환수"])
    assert ads["ad_revenue"] == 5 and ads["spend"] == 4 and "revenue" not in ads
    assert detect_kind(ads) == DataImport.Kind.ADS
    assert detect_kind(match_columns(["날짜", "검색어", "유입수", "결제수"])) == DataImport.Kind.KEYWORDS
    assert detect_kind(match_columns(["날짜", "방문수", "페이지뷰"])) == DataImport.Kind.TRAFFIC


@pytest.mark.parametrize(
    "value,expected",
    [("2026-09-01", date(2026, 9, 1)), ("2026.09.01.", date(2026, 9, 1)), ("20260901", date(2026, 9, 1)),
     (46266, date(2026, 9, 1)), ("합계", None), ("2026-13-01", None)],
)
def test_parse_date(value, expected):
    assert parse_date(value) == expected


def test_parse_number():
    assert parse_number("1,234원") == 1234
    assert parse_number("3.5%") == 3.5
    assert parse_number("-") == 0
    assert parse_number(None) == 0


def test_import_sales_csv_cp949_with_title_rows(store):
    csv_text = (
        "스마트스토어 상품 성과 리포트\n조회기간: 2026.09.01~2026.09.02\n"
        "일자,상품명,결제수,결제상품수량,결제금액\n"
        "2026.09.01,린넨 원피스,3,3,\"119,700\"\n"
        "2026.09.01,린넨 원피스,1,1,39900\n"
        "2026.09.02,버킷햇,2,2,31800\n"
        "합계,,6,6,191400\n"
    )
    result = import_report(store, "report.csv", csv_text.encode("cp949"))
    assert result.kind == DataImport.Kind.SALES
    assert result.rows == 2 and result.skipped == 1
    dress = DailySales.objects.get(product__name="린넨 원피스")
    assert (dress.orders, dress.units, dress.revenue) == (4, 4, 159_600)  # duplicate rows summed

    # Re-importing the same period replaces instead of double counting.
    import_report(store, "report.csv", csv_text.encode("cp949"))
    assert DailySales.objects.count() == 2
    assert DataImport.objects.count() == 2


def test_import_xlsx_keywords(store):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["날짜", "유입 키워드", "유입수", "결제수", "결제금액"])
    ws.append([date(2026, 9, 1), "린넨원피스", 120, 4, 159600])
    ws.append([date(2026, 9, 1), "", 5, 0, 0])
    buffer = io.BytesIO()
    wb.save(buffer)
    result = import_report(store, "keywords.xlsx", buffer.getvalue())
    assert result.kind == DataImport.Kind.KEYWORDS and result.rows == 1
    assert KeywordInflow.objects.get().visits == 120


def test_import_errors_are_actionable(store):
    with pytest.raises(ImportError_, match="날짜"):
        import_report(store, "x.csv", "상품,금액\na,1\n".encode())
    with pytest.raises(ImportError_, match="광고비"):
        import_report(store, "x.csv", "날짜,키워드\n2026-09-01,a\n".encode(), kind=DataImport.Kind.ADS)
    with pytest.raises(ImportError_, match="엑셀"):
        import_report(store, "x.xlsx", b"not a zip")


# ----------------------------------------------------------------- analytics
def _sales(store, product, day, revenue, orders=1):
    DailySales.objects.create(store=store, product=product, date=day, orders=orders, units=orders, revenue=revenue)


def test_dashboard_compares_periods_and_resolves_store_rows(owner, store):
    coupang = Store.objects.create(owner=owner, marketplace="coupang", name="쿠팡점")
    dress = Product.objects.create(store=store, name="원피스")
    end = date(2026, 9, 30)
    for i in range(14):
        day = end - timedelta(days=i)
        revenue = 20_000 if i < 7 else 10_000
        _sales(store, dress, day, revenue)
        _sales(store, None, day, 999_999)  # store-level row is ignored when product rows exist
        _sales(coupang, None, day, 5_000)  # store with only store-level rows
    KeywordStat.objects.create(scope=f"u{owner.id}", normalized="린넨원피스", keyword="린넨원피스", pc_searches=1000, mobile_searches=9000)
    KeywordInflow.objects.create(store=store, date=end, keyword="린넨 원피스", visits=70, orders=7, revenue=100)
    AdDaily.objects.create(store=store, date=end, keyword="린넨원피스", spend=100_000, revenue=90_000, clicks=200)

    data = dashboard(owner, days=7)
    kpis = {k["key"]: k for k in data["kpis"]}
    assert kpis["revenue"]["value"] == 7 * 25_000
    assert kpis["revenue"]["prev"] == 7 * 15_000
    assert kpis["revenue"]["delta"] == pytest.approx(66.7)
    assert kpis["roas"]["value"] == 90
    assert [c["key"] for c in data["channels"]] == ["naver", "coupang"]
    assert data["channels"][0]["share"] == 80.0
    assert data["products"][0]["delta"] == 100.0
    keyword = data["keywords"][0]
    assert keyword["market"] == 10_000 and keyword["capture"] == pytest.approx(70 / (10_000 * 7 / 30) * 100, abs=0.1)
    assert len(data["daily"]["revenue"]) == 7

    titles = [i["title"] for i in build_insights(data)]
    assert any("매출" in t and "증가" in t for t in titles)
    assert any("ROAS 90%" in t for t in titles)

    only_coupang = dashboard(owner, days=7, store_id=coupang.id)
    assert only_coupang["kpis"][0]["value"] == 35_000


def test_dashboard_without_data(owner):
    assert dashboard(owner) is None
    assert overview_for_agent(owner)["has_data"] is False


def test_demo_store_is_rich_and_replaceable(owner):
    create_demo(owner, days=60)
    create_demo(owner, days=60)
    assert Store.objects.filter(owner=owner).count() == 2
    data = dashboard(owner, days=30)
    assert data["is_demo"]
    assert {k["key"] for k in data["kpis"]} == {"revenue", "orders", "aov", "conversion", "roas"}
    assert data["ads"]["keywords"] and data["keywords"] and data["products"]
    overview = overview_for_agent(owner, 30)
    assert overview["has_data"] and overview["demo"] and overview["insights"]
    json.dumps(overview)  # must be JSON-serializable for the agent


# -------------------------------------------------------------------- charts
def test_chart_helpers():
    assert nice_ticks(2_870_000) == [0, 1_000_000, 2_000_000, 3_000_000]
    assert won_short(3_000_000) == "300만" and won_short(150_000_000) == "1.5억" and won_short(0) == "0"
    days = [date(2026, 9, 1) + timedelta(days=i) for i in range(10)]
    chart = line_chart(days, [{"name": "a", "values": list(range(10)), "role": "primary"}, {"name": "b", "values": [5] * 10, "role": "compare"}])
    assert chart["series"][0]["area"] and not chart["series"][1]["area"]
    assert chart["hover"]["labels"][0] == "9월 1일"
    cols = column_chart([{"label": "월", "value": 10, "highlight": False}, {"label": "화", "value": 0, "highlight": True}])
    assert cols["cols"][1]["d"].startswith("M")


# --------------------------------------------------------------------- views
@pytest.fixture
def seller(client, owner):
    client.force_login(owner)
    return owner


def test_dashboard_empty_then_demo(client, seller):
    page = client.get("/").content.decode()
    assert "데모 데이터로 둘러보기" in page
    response = client.post("/dashboard/demo/")
    assert response.status_code == 302
    page = client.get("/?days=90").content.decode()
    assert "다음 액션" in page and "revenue-hover" in page and "표로 보기" in page
    assert "데모 데이터를 보고 있어요" in page


def test_upload_creates_store_and_imports(client, seller):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("sales.csv", "날짜,결제금액,결제수\n2026-09-01,50000,2\n".encode())
    response = client.post("/data/", {"file": upload, "store": "new", "new_store": "새가게", "marketplace": "coupang"}, follow=True)
    assert "판매 실적 1행을 가져왔어요" in response.content.decode()
    store = Store.objects.get(name="새가게")
    assert store.marketplace == "coupang" and store.sales.get().revenue == 50_000

    bad = SimpleUploadedFile("bad.csv", "a,b\n1,2\n".encode())
    response = client.post("/data/", {"file": bad, "store": store.id}, follow=True)
    assert "날짜 열을 찾지 못했어요" in response.content.decode()

    client.post(f"/data/stores/{store.id}/delete/")
    assert not Store.objects.exists()


def test_store_overview_internal_endpoint(client, owner):
    create_demo(owner, days=40)
    response = client.post(
        "/internal/store/overview", data=json.dumps({"days": 7}), content_type="application/json",
        HTTP_AUTHORIZATION="Bearer test-token", HTTP_X_PIVEND_USER=str(owner.id),
    )
    assert response.status_code == 200
    assert response.json()["period"]["days"] == 7
    bad = client.post(
        "/internal/store/overview", data=json.dumps({"days": 3}), content_type="application/json",
        HTTP_AUTHORIZATION="Bearer test-token", HTTP_X_PIVEND_USER=str(owner.id),
    )
    assert bad.status_code == 400


def test_chat_embed_mode_can_be_framed(client, seller):
    response = client.get("/chat/?embed=1")
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    page = response.content.decode()
    assert 'class="embed' in page and "sidebar" not in page and '<base target="_top">' in page
