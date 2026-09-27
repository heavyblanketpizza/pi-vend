"""Naver 검색광고 API client — only the 키워드도구 (RelKwdStat) endpoint for now.

Docs: https://naver.github.io/searchad-apidoc/ (GitHub: naver/searchad-apidoc)
Auth: X-API-KEY / X-Customer / X-Timestamp headers plus X-Signature, the
base64 HMAC-SHA256 of "{timestamp}.{METHOD}.{uri}" keyed with the secret key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass

import httpx
from django.conf import settings

from .errors import NaverAPIError, NaverNotConfigured

BASE_URL = "https://api.searchad.naver.com"
KEYWORDSTOOL_URI = "/keywordstool"
# The keyword tool accepts at most five hint keywords per request.
MAX_HINT_KEYWORDS = 5


def sign(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    message = f"{timestamp}.{method}.{uri}".encode()
    digest = hmac.new(secret_key.encode(), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def parse_count(value) -> tuple[int, bool]:
    """Search counts come back as ints, or the string "< 10" for tiny volumes.

    Returns (count, under_10). Values under 10 are reported as 0.
    """
    if isinstance(value, (int, float)):
        return int(value), False
    text = str(value).strip()
    if text.startswith("<"):
        return 0, True
    try:
        return int(float(text.replace(",", ""))), False
    except ValueError:
        return 0, False


def parse_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class KeywordToolRow:
    keyword: str
    pc_searches: int
    mobile_searches: int
    pc_under_10: bool
    mobile_under_10: bool
    pc_clicks: float
    mobile_clicks: float
    pc_ctr: float
    mobile_ctr: float
    competition: str  # 경쟁정도: "낮음" / "중간" / "높음"
    ad_depth: float  # plAvgDepth: average number of ads shown

    @classmethod
    def from_api(cls, row: dict) -> "KeywordToolRow":
        pc, pc_low = parse_count(row.get("monthlyPcQcCnt"))
        mobile, mobile_low = parse_count(row.get("monthlyMobileQcCnt"))
        return cls(
            keyword=str(row.get("relKeyword", "")),
            pc_searches=pc,
            mobile_searches=mobile,
            pc_under_10=pc_low,
            mobile_under_10=mobile_low,
            pc_clicks=parse_float(row.get("monthlyAvePcClkCnt")),
            mobile_clicks=parse_float(row.get("monthlyAveMobileClkCnt")),
            pc_ctr=parse_float(row.get("monthlyAvePcCtr")),
            mobile_ctr=parse_float(row.get("monthlyAveMobileCtr")),
            competition=str(row.get("compIdx") or ""),
            ad_depth=parse_float(row.get("plAvgDepth")),
        )


class SearchAdClient:
    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        customer_id: str | None = None,
        http: httpx.Client | None = None,
    ):
        self.api_key = api_key if api_key is not None else settings.NAVER_SEARCHAD_API_KEY
        self.secret_key = secret_key if secret_key is not None else settings.NAVER_SEARCHAD_SECRET_KEY
        self.customer_id = customer_id if customer_id is not None else settings.NAVER_SEARCHAD_CUSTOMER_ID
        if not (self.api_key and self.secret_key and self.customer_id):
            raise NaverNotConfigured(
                "Naver 검색광고 API is not configured "
                "(NAVER_SEARCHAD_API_KEY / NAVER_SEARCHAD_SECRET_KEY / NAVER_SEARCHAD_CUSTOMER_ID)."
            )
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=15.0)

    def _headers(self, method: str, uri: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Timestamp": timestamp,
            "X-API-KEY": self.api_key,
            "X-Customer": str(self.customer_id),
            "X-Signature": sign(timestamp, method, uri, self.secret_key),
        }

    def keywordstool(self, hint_keywords: list[str]) -> list[KeywordToolRow]:
        """Search volume for the hint keywords plus related keywords.

        Hint keywords can't contain spaces, so they're stripped here.
        """
        hints = [k.replace(" ", "") for k in hint_keywords if k.strip()]
        if not hints:
            return []
        if len(hints) > MAX_HINT_KEYWORDS:
            raise ValueError(f"keywordstool accepts at most {MAX_HINT_KEYWORDS} keywords per call")

        params = {"hintKeywords": ",".join(hints), "showDetail": "1"}
        for attempt in range(3):
            try:
                response = self.http.get(
                    KEYWORDSTOOL_URI, params=params, headers=self._headers("GET", KEYWORDSTOOL_URI)
                )
            except httpx.HTTPError as exc:
                raise NaverAPIError(f"keywordstool request failed: {exc}") from exc
            if response.status_code == 429 and attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            break
        if response.status_code != 200:
            raise NaverAPIError(
                f"keywordstool failed with HTTP {response.status_code}",
                status_code=response.status_code,
                body=response.text[:500],
            )
        rows = response.json().get("keywordList", [])
        return [KeywordToolRow.from_api(row) for row in rows]
