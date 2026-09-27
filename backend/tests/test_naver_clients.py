import base64
import hashlib
import hmac

import httpx
import pytest
import respx

from pivend.naver.errors import NaverAPIError, NaverNotConfigured
from pivend.naver.openapi import NaverOpenAPIClient, clean_html, resolve_category
from pivend.naver.searchad import KeywordToolRow, SearchAdClient, parse_count, sign


def test_sign_matches_hmac_sha256_base64():
    expected = base64.b64encode(
        hmac.new(b"secret", b"1700000000000.GET./keywordstool", hashlib.sha256).digest()
    ).decode()
    assert sign("1700000000000", "GET", "/keywordstool", "secret") == expected


@pytest.mark.parametrize(
    "value,expected",
    [(1200, (1200, False)), ("< 10", (0, True)), ("3,400", (3400, False)), (None, (0, False))],
)
def test_parse_count(value, expected):
    assert parse_count(value) == expected


def test_missing_credentials_raise():
    with pytest.raises(NaverNotConfigured):
        SearchAdClient(api_key="", secret_key="", customer_id="")
    with pytest.raises(NaverNotConfigured):
        NaverOpenAPIClient(client_id="", client_secret="")


@respx.mock
def test_keywordstool_signs_request_and_parses_rows():
    route = respx.get("https://api.searchad.naver.com/keywordstool").mock(
        return_value=httpx.Response(
            200,
            json={
                "keywordList": [
                    {
                        "relKeyword": "린넨원피스",
                        "monthlyPcQcCnt": 2400,
                        "monthlyMobileQcCnt": 18100,
                        "monthlyAvePcClkCnt": 12.5,
                        "monthlyAveMobileClkCnt": 210.3,
                        "monthlyAvePcCtr": 0.55,
                        "monthlyAveMobileCtr": 1.2,
                        "plAvgDepth": 15,
                        "compIdx": "높음",
                    },
                    {"relKeyword": "린넨원피스빅사이즈", "monthlyPcQcCnt": "< 10", "monthlyMobileQcCnt": 40, "compIdx": "낮음"},
                ]
            },
        )
    )
    client = SearchAdClient(api_key="key", secret_key="secret", customer_id="123")
    rows = client.keywordstool(["린넨 원피스"])

    request = route.calls.last.request
    assert request.url.params["hintKeywords"] == "린넨원피스"
    assert request.headers["X-API-KEY"] == "key"
    assert request.headers["X-Customer"] == "123"
    assert request.headers["X-Signature"] == sign(request.headers["X-Timestamp"], "GET", "/keywordstool", "secret")

    assert rows[0] == KeywordToolRow(
        keyword="린넨원피스", pc_searches=2400, mobile_searches=18100, pc_under_10=False,
        mobile_under_10=False, pc_clicks=12.5, mobile_clicks=210.3, pc_ctr=0.55,
        mobile_ctr=1.2, competition="높음", ad_depth=15.0,
    )
    assert rows[1].pc_under_10 and rows[1].pc_searches == 0 and rows[1].mobile_searches == 40


def test_keywordstool_rejects_more_than_five_hints():
    client = SearchAdClient(api_key="k", secret_key="s", customer_id="1")
    with pytest.raises(ValueError):
        client.keywordstool(["a", "b", "c", "d", "e", "f"])


@respx.mock
def test_keywordstool_raises_on_http_error():
    respx.get("https://api.searchad.naver.com/keywordstool").mock(return_value=httpx.Response(403, text="denied"))
    client = SearchAdClient(api_key="k", secret_key="s", customer_id="1")
    with pytest.raises(NaverAPIError) as exc:
        client.keywordstool(["원피스"])
    assert exc.value.status_code == 403


@respx.mock
def test_shopping_search_cleans_titles():
    route = respx.get("https://openapi.naver.com/v1/search/shop.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 523000,
                "items": [
                    {
                        "title": "<b>린넨</b> 원피스 &amp; 셔츠",
                        "lprice": "29900",
                        "hprice": "",
                        "mallName": "스토어A",
                        "productId": 123,
                        "productType": "2",
                        "brand": "",
                        "maker": "",
                        "category1": "패션의류",
                        "category2": "여성의류",
                        "category3": "원피스",
                        "category4": "",
                    }
                ],
            },
        )
    )
    client = NaverOpenAPIClient(client_id="id", client_secret="secret")
    result = client.shopping_search("린넨 원피스", display=500)

    request = route.calls.last.request
    assert request.headers["X-Naver-Client-Id"] == "id"
    assert request.url.params["display"] == "100"
    assert result.total == 523000
    item = result.items[0]
    assert item.title == "린넨 원피스 & 셔츠"
    assert item.lprice == 29900 and item.hprice == 0
    assert item.categories == ("패션의류", "여성의류", "원피스")


def test_clean_html_and_categories():
    assert clean_html("<b>a</b> &lt;b&gt;") == "a <b>"
    assert resolve_category("패션의류") == "50000000"
    assert resolve_category("50000008") == "50000008"
    with pytest.raises(ValueError):
        resolve_category("없는카테고리")


@respx.mock
def test_network_failures_become_naver_api_errors():
    respx.get("https://api.searchad.naver.com/keywordstool").mock(side_effect=httpx.ConnectError("refused"))
    respx.get("https://openapi.naver.com/v1/search/shop.json").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(NaverAPIError, match="request failed"):
        SearchAdClient(api_key="k", secret_key="s", customer_id="1").keywordstool(["원피스"])
    with pytest.raises(NaverAPIError, match="request failed"):
        NaverOpenAPIClient(client_id="i", client_secret="s").shopping_search("원피스")
