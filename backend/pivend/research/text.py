"""Korean product-title text helpers."""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

# Characters that separate words inside product titles.
_SPLIT_RE = re.compile(r"[\s/,|·•+\[\]\(\)\{\}<>【】「」『』:;!?~★☆♥♡◆◇■□▶▷※#&\"'`]+")


def normalize_keyword(keyword: str) -> str:
    """Naver treats "린넨 원피스" and "린넨원피스" as the same keyword tool entry."""
    return re.sub(r"\s+", "", keyword).upper()


def title_tokens(title: str) -> list[str]:
    return [t for t in _SPLIT_RE.split(title) if t]


@lru_cache(maxsize=1)
def _kiwi():
    try:
        from kiwipiepy import Kiwi
    except ImportError:  # pragma: no cover - optional dependency
        return None
    return Kiwi()


@lru_cache(maxsize=4096)
def compound_parts(token: str) -> tuple[str, ...]:
    """Split a compound like "셔츠원피스" into ("셔츠", "원피스").

    Only returns parts when the token is fully covered by two or more nouns of
    at least two characters; otherwise returns an empty tuple. Kiwi's general
    dictionary splits some product words badly (e.g. "린넨"), so anything
    that isn't a clean split is ignored.
    """
    if len(token) < 4 or not re.fullmatch(r"[가-힣]+", token):
        return ()
    kiwi = _kiwi()
    if kiwi is None:
        return ()
    tokens = kiwi.tokenize(token)
    parts = [t.form for t in tokens]
    tags = [t.tag for t in tokens]
    if len(parts) < 2 or "".join(parts) != token:
        return ()
    if not all(tag.startswith("NN") for tag in tags) or any(len(p) < 2 for p in parts):
        return ()
    return tuple(parts)


def token_frequencies(titles: list[str], top: int = 40) -> list[dict]:
    """How many titles contain each token (counted once per title)."""
    counts: Counter[str] = Counter()
    for title in titles:
        seen: set[str] = set()
        for token in title_tokens(title):
            seen.add(token)
            seen.update(compound_parts(token))
        counts.update(seen)
    return [
        {"token": token, "titles": n, "share": round(n / len(titles), 3)}
        for token, n in counts.most_common(top)
    ] if titles else []
