import json
import os

import httpx
import pytest
import respx
from django.contrib.auth.models import User

from pivend.assistant.models import Conversation
from pivend.listings.models import ListingDraft


@pytest.fixture
def seller(client, db):
    user = User.objects.create_user("seller", password="pw")
    client.force_login(user)
    return user


def sse(*events):
    return "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)


@respx.mock
def test_send_message_streams_and_saves_transcript(client, seller):
    transcript = [
        {"role": "user", "content": "안녕", "timestamp": 1},
        {"role": "assistant", "content": [{"type": "text", "text": "안녕하세요"}], "stopReason": "stop", "timestamp": 2},
    ]
    route = respx.post("http://agent.test/v1/chat").mock(
        return_value=httpx.Response(
            200,
            text=sse(
                {"type": "assistant_start"},
                {"type": "text_delta", "delta": "안녕하세요"},
                {"type": "done", "messages": transcript, "usage": {"input": 10, "output": 3}},
            ),
            headers={"Content-Type": "text/event-stream"},
        )
    )
    conversation = Conversation.objects.create(owner=seller)

    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "안녕"}), content_type="application/json")
    body = b"".join(response.streaming_content).decode()

    sent = json.loads(route.calls.last.request.content)
    assert sent == {"user_id": seller.id, "conversation_id": conversation.id, "messages": [], "message": "안녕"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"
    assert '"text_delta"' in body
    assert '"done"' in body and "timestamp" not in body  # transcript isn't sent to the browser

    conversation.refresh_from_db()
    assert conversation.messages == transcript
    assert conversation.title == "안녕"
    assert conversation.display_messages() == [
        {"role": "user", "text": "안녕"},
        {"role": "assistant", "text": "안녕하세요"},
    ]


@respx.mock
def test_send_message_reports_agent_errors(client, seller):
    respx.post("http://agent.test/v1/chat").mock(side_effect=httpx.ConnectError("refused"))
    conversation = Conversation.objects.create(owner=seller)
    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "hi"}), content_type="application/json")
    body = b"".join(response.streaming_content).decode()
    assert "Agent unavailable" in body


def test_cannot_use_someone_elses_conversation(client, seller):
    other = User.objects.create_user("other")
    conversation = Conversation.objects.create(owner=other)
    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "hi"}), content_type="application/json")
    assert response.status_code == 404


@respx.mock
def test_pages_render(client, seller):
    respx.get("http://agent.test/health").mock(return_value=httpx.Response(200, json={"ok": True, "provider": "anthropic", "model": "claude-opus-5"}))
    conversation = Conversation.objects.create(owner=seller, title="테스트")
    draft = ListingDraft.objects.create(owner=seller, product_name="원피스", title="린넨 원피스 원피스")

    chat = client.get(f"/chat/{conversation.id}/")
    assert chat.status_code == 200 and "claude-opus-5" in chat.content.decode()
    research = client.get("/research/?q=원피스")
    assert research.status_code == 200
    assert "NAVER_SEARCHAD" in research.content.decode()  # not configured in tests
    assert client.get("/drafts/").status_code == 200
    detail = client.get(f"/drafts/{draft.id}/")
    assert detail.status_code == 200 and "Repeated words" in detail.content.decode()


def test_login_required(client, db):
    response = client.get("/chat/")
    assert response.status_code == 302 and "/login/" in response["Location"]


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            kwargs = {}
            if os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"):
                kwargs["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE"]
            p.chromium.launch(**kwargs).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _chromium_available(), reason="Chromium for Playwright is not installed")
def test_real_render(seller, settings):
    from PIL import Image

    from pivend.listings.renderer import render_detail_page

    settings.PLAYWRIGHT_CHROMIUM_EXECUTABLE = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "")
    draft = ListingDraft.objects.create(owner=seller, product_name="원피스")
    render = render_detail_page(
        draft,
        {"sections": [{"type": "hero", "headline": "시원한 린넨 원피스"}, {"type": "faq", "items": [{"q": "세탁?", "a": "손세탁"}]}]},
    )
    first = Image.open(f"{settings.MEDIA_ROOT}/{render.images[0]}")
    assert first.width == 860
    assert render.height > 300
