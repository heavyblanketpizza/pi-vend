"""Naver Developers open APIs: 쇼핑 검색 and 데이터랩 (검색어 트렌드, 쇼핑인사이트).

Docs: https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
      https://developers.naver.com/docs/serviceapi/datalab/search/search.md
      https://developers.naver.com/docs/serviceapi/datalab/shopping/shopping.md
Auth: X-Naver-Client-Id / X-Naver-Client-Secret headers.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import httpx

from .errors import OPENAPI_NOT_CONFIGURED, NaverAPIError, NaverNotConfigured

BASE_URL = "https://openapi.naver.com"

# Top-level 네이버쇼핑 categories (cid) used by 쇼핑인사이트.
SHOPPING_CATEGORIES = {
    "패션의류": "50000000",
    "패션잡화": "50000001",
    "화장품/미용": "50000002",
    "디지털/가전": "50000003",
    "가구/인테리어": "50000004",
    "출산/육아": "50000005",
    "식품": "50000006",
    "스포츠/레저": "50000007",
    "생활/건강": "50000008",
    "여가/생활편의": "50000009",
}

_TAG_RE = re.compile(r"<[^>]+>")


def clean_html(text: str) -> str:
    """Shopping search titles wrap matches in <b> tags and escape entities."""
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def resolve_category(category: str) -> str:
    """Accept a cid ("50000000") or a top-level category name ("패션의류")."""
    category = category.strip()
    if category.isdigit():
        return category
    if category in SHOPPING_CATEGORIES:
        return SHOPPING_CATEGORIES[category]
    raise ValueError(
        f"Unknown category {category!r}. Use a cid or one of: {', '.join(SHOPPING_CATEGORIES)}"
    )


@dataclass(frozen=True)
class ShoppingItem:
    title: str
    link: str
    image: str
    lprice: int
    hprice: int
    mall_name: str
    product_id: str
    product_type: str
    brand: str
    maker: str
    categories: tuple[str, ...]

    @classmethod
    def from_api(cls, item: dict) -> "ShoppingItem":
        def to_int(value) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        categories = tuple(
            c for c in (item.get(f"category{i}", "") for i in range(1, 5)) if c
        )
        return cls(
            title=clean_html(item.get("title", "")),
            link=item.get("link", ""),
            image=item.get("image", ""),
            lprice=to_int(item.get("lprice")),
            hprice=to_int(item.get("hprice")),
            mall_name=item.get("mallName", ""),
            product_id=str(item.get("productId", "")),
            product_type=str(item.get("productType", "")),
            brand=item.get("brand", ""),
            maker=item.get("maker", ""),
            categories=categories,
        )

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "image": self.image,
            "lprice": self.lprice,
            "hprice": self.hprice,
            "mall_name": self.mall_name,
            "product_id": self.product_id,
            "product_type": self.product_type,
            "brand": self.brand,
            "maker": self.maker,
            "categories": list(self.categories),
        }


@dataclass(frozen=True)
class ShoppingSearchResult:
    total: int
    items: list[ShoppingItem]


class NaverOpenAPIClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        http: httpx.Client | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        if not (self.client_id and self.client_secret):
            raise NaverNotConfigured(OPENAPI_NOT_CONFIGURED)
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=15.0)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }

    def _send(self, method: str, path: str, what: str, **kwargs) -> dict:
        try:
            response = self.http.request(method, path, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise NaverAPIError(f"{what} request failed: {exc}") from exc
        return self._check(response, what)

    def _check(self, response: httpx.Response, what: str) -> dict:
        if response.status_code != 200:
            raise NaverAPIError(
                f"{what} failed with HTTP {response.status_code}",
                status_code=response.status_code,
                body=response.text[:500],
            )
        return response.json()

    def shopping_search(
        self, query: str, display: int = 40, start: int = 1, sort: str = "sim"
    ) -> ShoppingSearchResult:
        """Up to 100 results per call; `start` can't exceed 1000."""
        if sort not in {"sim", "date", "asc", "dsc"}:
            raise ValueError("sort must be one of sim, date, asc, dsc")
        params = {
            "query": query,
            "display": max(1, min(display, 100)),
            "start": max(1, min(start, 1000)),
            "sort": sort,
        }
        data = self._send("GET", "/v1/search/shop.json", "shopping search", params=params)
        return ShoppingSearchResult(
            total=int(data.get("total", 0)),
            items=[ShoppingItem.from_api(item) for item in data.get("items", [])],
        )

    def search_trend(
        self,
        keyword_groups: dict[str, list[str]],
        start_date: str,
        end_date: str,
        time_unit: str = "month",
        device: str | None = None,
        gender: str | None = None,
        ages: list[str] | None = None,
    ) -> dict:
        """데이터랩 검색어 트렌드. Up to 5 groups; ratios are relative (max = 100)."""
        body: dict = {
            "startDate": start_date,
            "endDate": end_date,
            "timeUnit": time_unit,
            "keywordGroups": [
                {"groupName": name, "keywords": keywords[:20]}
                for name, keywords in list(keyword_groups.items())[:5]
            ],
        }
        if device:
            body["device"] = device
        if gender:
            body["gender"] = gender
        if ages:
            body["ages"] = ages
        return self._send("POST", "/v1/datalab/search", "datalab search trend", json=body)

    def shopping_keyword_trend(
        self,
        category: str,
        keywords: list[str],
        start_date: str,
        end_date: str,
        time_unit: str = "month",
        device: str | None = None,
        gender: str | None = None,
        ages: list[str] | None = None,
    ) -> dict:
        """쇼핑인사이트 키워드별 트렌드 within a category (click ratios, max = 100)."""
        body: dict = {
            "startDate": start_date,
            "endDate": end_date,
            "timeUnit": time_unit,
            "category": resolve_category(category),
            "keyword": [{"name": k, "param": [k]} for k in keywords[:5]],
        }
        if device:
            body["device"] = device
        if gender:
            body["gender"] = gender
        if ages:
            body["ages"] = ages
        return self._send(
            "POST", "/v1/datalab/shopping/category/keywords", "datalab shopping keyword trend", json=body
        )
