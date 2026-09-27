import json
from pathlib import Path

import pytest
from django.contrib.auth.models import User

from pivend.listings import renderer
from pivend.listings.models import DetailPageRender, ListingDraft

AUTH = {"HTTP_AUTHORIZATION": "Bearer test-token"}


@pytest.fixture
def user(db):
    return User.objects.create_user("seller", password="pw")


def call(client, user, path, body=None, method="post", **headers):
    kwargs = {**AUTH, "HTTP_X_PIVEND_USER": str(user.id), **headers}
    if method == "get":
        return client.get(f"/internal/{path}", **kwargs)
    return client.post(f"/internal/{path}", data=json.dumps(body or {}), content_type="application/json", **kwargs)


def test_rejects_bad_token_and_unknown_user(client, user):
    response = client.post("/internal/listings/check-title", data="{}", content_type="application/json", HTTP_AUTHORIZATION="Bearer nope")
    assert response.status_code == 401
    response = client.post("/internal/listings/check-title", data="{}", content_type="application/json", **AUTH, HTTP_X_PIVEND_USER="999")
    assert response.status_code == 403


def test_method_and_body_validation(client, user):
    assert call(client, user, "listings/check-title", method="get").status_code == 405
    response = client.post(
        "/internal/listings/check-title", data="not json", content_type="application/json", **AUTH, HTTP_X_PIVEND_USER=str(user.id)
    )
    assert response.status_code == 400
    assert call(client, user, "research/keyword-stats", {"keywords": "not a list"}).status_code == 400


def test_unconfigured_naver_api_returns_503(client, user):
    response = call(client, user, "research/keyword-stats", {"keywords": ["원피스"]})
    assert response.status_code == 503
    assert response.json()["code"] == "not_configured"
    assert "NAVER_SEARCHAD" in response.json()["error"]


def test_check_title(client, user):
    response = call(client, user, "listings/check-title", {"title": "린넨 원피스 원피스", "target_keywords": ["린넨"]})
    assert response.status_code == 200
    assert any(i["code"] == "repeated_words" for i in response.json()["issues"])


def test_draft_lifecycle_is_scoped_to_owner(client, user):
    created = call(client, user, "listings/drafts", {"product_name": "린넨 원피스", "title": "린넨 원피스 여름", "tags": ["여름원피스"]})
    assert created.status_code == 200
    draft = created.json()
    assert draft["url"] == f"http://testserver/drafts/{draft['id']}/"

    updated = call(client, user, "listings/drafts", {"id": draft["id"], "marketplace": "coupang", "attributes": {"소재": "린넨"}})
    assert updated.json()["marketplace"] == "coupang"
    assert updated.json()["title"] == "린넨 원피스 여름"  # untouched fields stay

    listed = call(client, user, "listings/drafts", method="get").json()["drafts"]
    assert [d["id"] for d in listed] == [draft["id"]]

    other = User.objects.create_user("other")
    assert call(client, other, f"listings/drafts/{draft['id']}", method="get").status_code == 400
    assert call(client, other, "listings/drafts", {"id": draft["id"], "title": "x"}).status_code == 400
    assert call(client, user, "listings/drafts", {"title": "no product name"}).status_code == 400
    assert call(client, user, "listings/drafts", {"id": draft["id"], "marketplace": "gmarket"}).status_code == 400


def test_render_saves_spec_and_images(client, user, monkeypatch, settings):
    monkeypatch.setattr(renderer, "screenshot_html", lambda html: _png(860, 4200))
    draft = ListingDraft.objects.create(owner=user, product_name="원피스")
    spec = {"sections": [{"type": "hero", "headline": "시원한 원피스"}]}

    response = call(client, user, f"listings/drafts/{draft.id}/render", {"detail_page": spec})
    assert response.status_code == 200
    body = response.json()
    assert body["draft_url"].endswith(f"/drafts/{draft.id}/")
    assert len(body["images"]) == 2  # 4200px split at 3000px
    render = DetailPageRender.objects.get()
    assert all((Path(settings.MEDIA_ROOT) / p).exists() for p in render.images)
    draft.refresh_from_db()
    assert draft.detail_page["sections"][0]["headline"] == "시원한 원피스"

    invalid = call(client, user, f"listings/drafts/{draft.id}/render", {"detail_page": {"sections": [{"type": "hero"}]}})
    assert invalid.status_code == 400
    assert invalid.json()["details"] == ["sections[0].headline is required for 'hero' sections"]


def _png(width, height):
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()
