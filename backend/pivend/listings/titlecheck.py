"""Heuristic checks for marketplace product titles (상품명).

These encode widely-shared seller guidance, not an official validator:
- Naver's 상품명 guide asks for brand + product + key attributes and treats
  repeated keywords, promotional phrases and decorative symbols as abuse.
- Both marketplaces cap titles at 100 characters; shorter titles (~50 chars)
  tend to rank better on Naver because relevance is diluted less.
"""

from __future__ import annotations

import re
from collections import Counter

from pivend.research.text import normalize_keyword, title_tokens

HARD_LIMIT = 100
RECOMMENDED_MAX = 50

PROMO_TERMS = [
    "무료배송", "최저가", "특가", "할인", "세일", "이벤트", "사은품", "증정", "당일발송",
    "당일배송", "빠른배송", "쿠폰", "적립", "한정수량", "품절임박", "best", "베스트", "인기",
    "추천", "대박", "초특가", "sale",
]
DECORATIVE_RE = re.compile(r"[★☆♥♡◆◇■□▶▷※♣♠●○◎!~]")


def check_title(
    title: str,
    marketplace: str = "naver",
    target_keywords: list[str] | None = None,
    brand: str | None = None,
) -> dict:
    title = title.strip()
    issues: list[dict] = []

    def issue(level: str, code: str, message: str):
        issues.append({"level": level, "code": code, "message": message})

    length = len(title)
    if length == 0:
        issue("error", "empty", "Title is empty.")
    elif length > HARD_LIMIT:
        issue("error", "too_long", f"{length} characters; the limit is {HARD_LIMIT}.")
    elif length > RECOMMENDED_MAX:
        issue(
            "warning",
            "long",
            f"{length} characters. Titles over ~{RECOMMENDED_MAX} dilute keyword relevance.",
        )

    tokens = title_tokens(title)
    repeats = [t for t, n in Counter(t.lower() for t in tokens).items() if n > 1]
    if repeats:
        issue(
            "warning",
            "repeated_words",
            f"Repeated words: {', '.join(repeats)}. Repeating keywords reads as stuffing and can be penalized.",
        )

    lowered = title.lower()
    promos = [
        term
        for term in PROMO_TERMS
        if (re.search(rf"\b{term}\b", lowered) if term.isascii() else term in lowered)
    ]
    if promos:
        issue(
            "warning",
            "promo_terms",
            f"Promotional terms: {', '.join(promos)}. Shipping/discount/event wording belongs in other fields, not the 상품명.",
        )

    decorative = sorted(set(DECORATIVE_RE.findall(title)))
    if decorative:
        issue("warning", "decorative_symbols", f"Decorative symbols: {' '.join(decorative)}.")

    compact = normalize_keyword(title)
    missing = [k for k in (target_keywords or []) if normalize_keyword(k) not in compact]
    covered = [k for k in (target_keywords or []) if k not in missing]
    if missing:
        issue("info", "missing_keywords", f"Target keywords not in the title: {', '.join(missing)}.")

    if brand:
        position = compact.find(normalize_keyword(brand))
        if position == -1:
            issue("info", "brand_missing", f"Brand '{brand}' is not in the title.")
        elif position > 0:
            issue("info", "brand_not_first", f"Brand '{brand}' usually leads the title (brand + product + attributes).")

    if marketplace == "coupang" and length and not brand:
        issue(
            "info",
            "coupang_brand",
            "Coupang requires brand information on listings; pass the brand to check its placement.",
        )

    return {
        "title": title,
        "marketplace": marketplace,
        "length": length,
        "word_count": len(tokens),
        "keywords_covered": covered,
        "keywords_missing": missing,
        "ok": not any(i["level"] == "error" for i in issues),
        "issues": issues,
        "note": "Heuristic check based on common seller guidance, not an official marketplace validator.",
    }
