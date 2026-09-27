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
        issue("error", "empty", "상품명이 비어 있어요.")
    elif length > HARD_LIMIT:
        issue("error", "too_long", f"{length}자예요. 최대 {HARD_LIMIT}자까지 입력할 수 있어요.")
    elif length > RECOMMENDED_MAX:
        issue(
            "warning",
            "long",
            f"{length}자예요. {RECOMMENDED_MAX}자를 넘으면 키워드 적합도가 분산될 수 있어요.",
        )

    tokens = title_tokens(title)
    repeats = [t for t, n in Counter(t.lower() for t in tokens).items() if n > 1]
    if repeats:
        issue(
            "warning",
            "repeated_words",
            f"반복된 단어: {', '.join(repeats)}. 같은 키워드를 반복하면 어뷰징으로 보일 수 있어요.",
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
            f"홍보 문구: {', '.join(promos)}. 배송·할인·이벤트 정보는 상품명이 아닌 다른 항목에 넣으세요.",
        )

    decorative = sorted(set(DECORATIVE_RE.findall(title)))
    if decorative:
        issue("warning", "decorative_symbols", f"장식용 특수문자: {' '.join(decorative)}. 검색 품질을 떨어뜨릴 수 있어요.")

    compact = normalize_keyword(title)
    missing = [k for k in (target_keywords or []) if normalize_keyword(k) not in compact]
    covered = [k for k in (target_keywords or []) if k not in missing]
    if missing:
        issue("info", "missing_keywords", f"상품명에 없는 타깃 키워드: {', '.join(missing)}.")

    if brand:
        position = compact.find(normalize_keyword(brand))
        if position == -1:
            issue("info", "brand_missing", f"브랜드 '{brand}'가 상품명에 없어요.")
        elif position > 0:
            issue("info", "brand_not_first", f"브랜드 '{brand}'는 상품명 맨 앞에 두는 게 일반적이에요 (브랜드 + 상품 + 속성).")

    if marketplace == "coupang" and length and not brand:
        issue(
            "info",
            "coupang_brand",
            "쿠팡은 브랜드 정보가 필수예요. 브랜드를 함께 넘기면 위치까지 점검해요.",
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
        "note": "마켓 공식 검증기가 아니라 셀러 가이드에 기반한 휴리스틱 점검이에요.",
    }
