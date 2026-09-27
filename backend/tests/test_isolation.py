"""One seller must never see or change another seller's data."""

import json

import pytest
from django.contrib.auth.models import User

from pivend.accounts.models import Credential
from pivend.assistant.models import Conversation
from pivend.listings.models import DetailPageRender, ListingDraft
from pivend.store.demo import create_demo
from pivend.store.models import Store

from .conftest import connect_llm, connect_naver


@pytest.fixture
def alice(db):
    user = User.objects.create_user("alice@example.com", email="alice@example.com", password="pw")
    create_demo(user, days=30)
    connect_naver(user)
    connect_llm(user, api_key="sk-alice-secret")
    draft = ListingDraft.objects.create(owner=user, product_name="앨리스 원피스", title="앨리스 비밀 상품명")
    DetailPageRender.objects.create(draft=draft, spec={}, html="", images=["detail-pages/1/x/01.jpg"])
    Conversation.objects.create(owner=user, title="앨리스 대화", messages=[{"role": "user", "content": "비밀"}])
    return user


@pytest.fixture
def bob(client, db):
    user = User.objects.create_user("bob@example.com", email="bob@example.com", password="pw")
    client.force_login(user)
    return user


def test_pages_show_only_own_data(client, alice, bob):
    for url in ["/", "/drafts/", "/chat/", "/data/", "/settings/", "/research/"]:
        page = client.get(url).content.decode()
        assert "앨리스" not in page and "하늘상점 쿠팡" not in page, url
    assert "데모 데이터로 둘러보기" in client.get("/").content.decode()
    assert "sk-alice-secret" not in client.get("/settings/").content.decode()


def test_cannot_reach_other_users_objects(client, alice, bob):
    draft = ListingDraft.objects.get(owner=alice)
    conversation = Conversation.objects.get(owner=alice)
    store = Store.objects.filter(owner=alice).first()
    assert client.get(f"/drafts/{draft.id}/").status_code == 404
    assert client.get(f"/drafts/{draft.id}/download/").status_code == 404
    assert client.post(f"/drafts/{draft.id}/approve/").status_code == 404
    assert client.post(f"/drafts/{draft.id}/render/").status_code == 404
    assert client.get(f"/chat/{conversation.id}/").status_code == 404
    assert client.post(f"/chat/{conversation.id}/delete/").status_code == 404
    assert client.post(f"/data/stores/{store.id}/delete/").status_code == 404
    assert client.get(f"/?store={store.id}").status_code == 200  # filter ignored, no data leaks
    assert "하늘상점" not in client.get(f"/?store={store.id}").content.decode()

    # Bob's settings actions only ever touch Bob's rows.
    client.post("/settings/connections/searchad/delete/")
    client.post("/settings/connections/llm/delete/")
    assert Credential.objects.filter(owner=alice).count() == 3
    assert ListingDraft.objects.get(id=draft.id).status == "draft"


def test_agent_acts_only_for_the_user_it_was_given(client, alice, bob):
    draft = ListingDraft.objects.get(owner=alice)
    headers = {"HTTP_AUTHORIZATION": "Bearer test-token", "HTTP_X_PIVEND_USER": str(bob.id)}
    assert client.get(f"/internal/listings/drafts/{draft.id}", **headers).status_code == 400
    listed = client.get("/internal/listings/drafts", **headers).json()
    assert listed["drafts"] == []
    overview = client.post("/internal/store/overview", data=json.dumps({"days": 30}), content_type="application/json", **headers).json()
    assert overview["has_data"] is False
    # Bob has no Naver keys: Alice's are never used on his behalf.
    response = client.post(
        "/internal/research/keyword-stats", data=json.dumps({"keywords": ["원피스"]}), content_type="application/json", **headers
    )
    assert response.status_code == 503


def test_chat_uses_the_senders_own_model_key(client, alice, bob):
    from pivend.accounts.services import llm_config

    assert llm_config(bob) is None
    conversation = Conversation.objects.create(owner=bob)
    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "hi"}), content_type="application/json")
    assert '"no_llm"' in b"".join(response.streaming_content).decode()
