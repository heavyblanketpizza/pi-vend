import io

import pytest
from PIL import Image

from pivend.accounts.netguard import is_public_host
from pivend.listings import renderer
from pivend.listings.detailpage import SpecError, validate_spec
from pivend.listings.titlecheck import check_title


def codes(result):
    return {i["code"] for i in result["issues"]}


def test_clean_title_passes():
    result = check_title("모던하우스 린넨 원피스 여름 셔츠 롱", target_keywords=["린넨원피스", "여름 셔츠"], brand="모던하우스")
    assert result["ok"]
    assert result["issues"] == []
    assert result["keywords_covered"] == ["린넨원피스", "여름 셔츠"]


def test_keyword_coverage_needs_adjacent_words():
    result = check_title("린넨 셔츠 원피스", target_keywords=["린넨 원피스"])
    assert result["keywords_missing"] == ["린넨 원피스"]


def test_title_issues_are_flagged():
    title = "★무료배송★ 린넨 원피스 원피스 여름 원피스 " + "가" * 60
    result = check_title(title, target_keywords=["린넨 원피스", "롱원피스"], brand="모던하우스")
    found = codes(result)
    assert {"long", "repeated_words", "promo_terms", "decorative_symbols", "missing_keywords", "brand_missing"} <= found
    assert result["keywords_covered"] == ["린넨 원피스"]
    assert result["keywords_missing"] == ["롱원피스"]


def test_title_hard_limit_is_error():
    result = check_title("가" * 101)
    assert not result["ok"]
    assert "too_long" in codes(result)


def test_ascii_promo_terms_need_word_boundaries():
    assert "promo_terms" not in codes(check_title("Bestway 수영장 튜브"))
    assert "promo_terms" in codes(check_title("여름 원피스 BEST"))


def test_validate_spec_cleans_and_applies_theme():
    spec = validate_spec(
        {
            "theme": {"accent": "#123456"},
            "sections": [
                {"type": "hero", "headline": "  시원한 원피스 ", "unknown": "dropped", "badges": ["린넨", ""]},
                {"type": "specs", "rows": [{"label": "소재", "value": "린넨"}]},
            ],
        }
    )
    assert spec["theme"]["accent"] == "#123456"
    assert spec["theme"]["background"] == "#FFFFFF"
    assert spec["sections"][0] == {"type": "hero", "headline": "시원한 원피스", "badges": ["린넨"]}


def test_validate_spec_reports_every_problem():
    with pytest.raises(SpecError) as exc:
        validate_spec(
            {
                "theme": {"accent": "red", "shadow": "#000000"},
                "sections": [
                    {"type": "hero"},
                    {"type": "carousel"},
                    {"type": "faq", "items": [{"q": "배송?"}]},
                    {"type": "feature", "headline": "x", "image_url": "javascript:alert(1)"},
                ],
            }
        )
    errors = " | ".join(exc.value.errors)
    assert "theme.accent must be a #RRGGBB color" in errors
    assert "theme.shadow" in errors
    assert "sections[0].headline is required" in errors
    assert "sections[1].type must be one of" in errors
    assert "sections[2].items[0].a is required" in errors
    assert "sections[3].image_url must be an http(s) URL" in errors


@pytest.mark.parametrize(
    "host,public",
    [("localhost", False), ("127.0.0.1", False), ("169.254.169.254", False), ("10.0.0.5", False), ("192.168.0.1", False), ("", False)],
)
def test_renderer_blocks_private_hosts(host, public):
    assert is_public_host(host) is public


def test_slice_image_splits_long_pages():
    buffer = io.BytesIO()
    Image.new("RGB", (860, 2500), "white").save(buffer, format="PNG")
    slices, height = renderer.slice_image(buffer.getvalue(), 1000)
    assert height == 2500
    assert [Image.open(io.BytesIO(s)).size for s in slices] == [(860, 1000), (860, 1000), (860, 500)]
