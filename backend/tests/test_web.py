import io
import json
import os
import zipfile
from datetime import timedelta

import httpx
import pytest
import respx
from django.contrib.auth.models import User
from django.utils import timezone

from pivend.assistant.models import Conversation
from pivend.listings.models import DetailPageRender, ListingDraft
from pivend.web.charts import area_chart, monotone_path, price_positions
from pivend.web.templatetags.ui import compact, month_label, reltime

from .conftest import connect_llm, connect_naver
from .test_research import FakeOpenAPI, FakeSearchAd


@pytest.fixture
def seller(client, db):
    user = User.objects.create_user("seller", password="pw")
    client.force_login(user)
    return user


def sse(*events):
    return "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)


# --------------------------------------------------------------------- chat
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
    connect_llm(seller)

    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "안녕"}), content_type="application/json")
    body = b"".join(response.streaming_content).decode()

    sent = json.loads(route.calls.last.request.content)
    assert sent == {
        "user_id": seller.id,
        "conversation_id": conversation.id,
        "messages": [],
        "message": "안녕",
        "llm": {
            "provider": "anthropic", "model": "claude-opus-5", "base_url": None, "api_key": "sk-ant-user",
            "reasoning": False, "thinking_format": None,
        },
    }
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"
    assert '"text_delta"' in body
    assert '"done"' in body and "timestamp" not in body  # transcript isn't sent to the browser

    conversation.refresh_from_db()
    assert conversation.messages == transcript
    assert conversation.title == "안녕"


@respx.mock
def test_send_message_reports_agent_errors(client, seller):
    respx.post("http://agent.test/v1/chat").mock(side_effect=httpx.ConnectError("refused"))
    conversation = Conversation.objects.create(owner=seller)
    connect_llm(seller)
    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "hi"}), content_type="application/json")
    body = b"".join(response.streaming_content).decode()
    assert "에이전트에 연결할 수 없어요" in body


@respx.mock
def test_send_message_needs_a_connected_model(client, seller):
    route = respx.post("http://agent.test/v1/chat")
    conversation = Conversation.objects.create(owner=seller)
    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "hi"}), content_type="application/json")
    body = b"".join(response.streaming_content).decode()
    assert '"no_llm"' in body and "API 연결" in body
    assert not route.called


def test_display_messages_include_tool_outcomes():
    conversation = Conversation(
        messages=[
            {"role": "user", "content": "상세페이지 만들어줘"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "만들어 볼게요."},
                    {"type": "toolCall", "id": "a", "name": "save_draft", "arguments": {"product_name": "원피스"}},
                ],
            },
            {"role": "toolResult", "toolCallId": "a", "content": [{"type": "text", "text": '{"id": 3}'}], "isError": False},
            {"role": "assistant", "content": [{"type": "toolCall", "id": "b", "name": "render_detail_page", "arguments": {}}]},
            {
                "role": "toolResult",
                "toolCallId": "b",
                "content": [{"type": "text", "text": '{"images": ["http://x/1.jpg"], "draft_url": "http://x/drafts/3/"}'}],
                "isError": False,
            },
            {"role": "assistant", "content": [{"type": "toolCall", "id": "c", "name": "check_title", "arguments": {"title": "x"}}]},
            {"role": "toolResult", "toolCallId": "c", "content": [{"type": "text", "text": "boom"}], "isError": True},
            {"role": "assistant", "content": [], "stopReason": "error", "errorMessage": "rate limited"},
        ]
    )
    shown = conversation.display_messages()
    assert shown[0] == {"role": "user", "text": "상세페이지 만들어줘"}
    assert shown[1] == {"role": "assistant", "text": "만들어 볼게요."}
    assert shown[2]["steps"][0] == {"name": "save_draft", "args": {"product_name": "원피스"}, "isError": False}
    render_step = shown[3]["steps"][0]
    assert render_step["images"] == ["http://x/1.jpg"] and render_step["draftUrl"] == "http://x/drafts/3/"
    assert shown[4]["steps"][0]["isError"] is True and shown[4]["steps"][0]["summary"] == "boom"
    assert shown[5] == {"role": "error", "text": "rate limited"}


def test_conversations_are_created_lazily_and_deletable(client, seller):
    page = client.get("/chat/")
    assert page.status_code == 200
    assert Conversation.objects.count() == 0
    assert "무엇을 팔고 계신가요?" in page.content.decode()

    created = client.post("/chat/new/").json()
    conversation = Conversation.objects.get(id=created["id"])
    assert created["send_url"] == f"/chat/{conversation.id}/send/"

    response = client.post(f"/chat/{conversation.id}/delete/", HTTP_REFERER=f"http://testserver/chat/{conversation.id}/")
    assert response.status_code == 302 and response["Location"] == "/chat/"
    assert not Conversation.objects.exists()


def test_cannot_use_someone_elses_conversation(client, seller):
    other = User.objects.create_user("other")
    conversation = Conversation.objects.create(owner=other)
    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "hi"}), content_type="application/json")
    assert response.status_code == 404
    assert client.post(f"/chat/{conversation.id}/delete/").status_code == 404


def test_chat_page_shows_history_sidebar_and_prefill(client, seller, agent_status):
    Conversation.objects.create(owner=seller, title="린넨 원피스 키워드", messages=[{"role": "user", "content": "안녕"}])
    old = Conversation.objects.create(owner=seller, title="지난 대화")
    Conversation.objects.filter(id=old.id).update(updated_at=timezone.now() - timedelta(days=10))

    assert "AI 모델 미연결" in client.get("/chat/").content.decode()
    connect_llm(seller)
    page = client.get("/chat/?prompt=상품명 추천").content.decode()
    assert "린넨 원피스 키워드" in page and "지난 대화" in page
    assert "오늘" in page and "이전" in page
    assert "claude-opus-5" in page
    assert "상품명 추천</textarea>" in page

    agent_status.clear()
    agent_status.update({"online": False, "error": "refused"})
    assert "에이전트 오프라인" in client.get("/chat/").content.decode()


def test_login_required_and_login_page(client, db):
    response = client.get("/chat/")
    assert response.status_code == 302 and "/login/" in response["Location"]
    assert "팔리는 상품명과" in client.get("/login/").content.decode()


# ----------------------------------------------------------------- research
def test_research_without_keys_shows_setup(client, seller):
    page = client.get("/research/?q=원피스").content.decode()
    assert "네이버 데이터 연결이 필요해요" in page
    assert "/settings/" in page


@pytest.mark.django_db
def test_research_page_renders_all_sections(client, seller, settings, monkeypatch):
    from pivend.research import services

    connect_naver(seller)
    used = []
    monkeypatch.setattr(services, "searchad_client", lambda account: used.append(account) or FakeSearchAd())
    monkeypatch.setattr(services, "openapi_client", lambda account: FakeOpenAPI())

    page = client.get("/research/?q=린넨 원피스").content.decode()
    assert "네이버 데이터 연결이 필요해요" not in page
    assert "20,000" in page  # monthly searches
    assert "18만" in page  # listing count, compact
    assert "9.0" in page  # competition ratio
    assert 'class="line"' in page  # trend chart
    assert "여름원피스" in page  # related keywords
    assert "29,900" in page  # median price
    assert "패션의류 &gt; 여성의류 &gt; 원피스" in page
    assert "에이전트에게 상품명 맡기기" in page

    assert client.session["recent_searches"] == ["린넨 원피스"]
    assert used[0].scope == f"u{seller.id}" and used[0].searchad_keys["customer_id"] == "1234567"


# ------------------------------------------------------------------- drafts
def _render(draft, media_root, n=2):
    from PIL import Image

    paths = []
    folder = media_root / "detail-pages" / str(draft.id) / "r1"
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        Image.new("RGB", (860, 100), "white").save(folder / f"0{i}.jpg")
        paths.append(f"detail-pages/{draft.id}/r1/0{i}.jpg")
    return DetailPageRender.objects.create(draft=draft, spec={}, html="", images=paths, height=200)


def test_drafts_list_filters_and_covers(client, seller, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    approved = ListingDraft.objects.create(owner=seller, product_name="승인 상품", status="approved")
    pending = ListingDraft.objects.create(owner=seller, product_name="검토 상품")
    _render(pending, tmp_path)

    page = client.get("/drafts/").content.decode()
    assert "승인 상품" in page and "검토 상품" in page
    assert f"/media/detail-pages/{pending.id}/r1/01.jpg" in page
    filtered = client.get("/drafts/?status=approved").content.decode()
    assert "승인 상품" in filtered and "검토 상품" not in filtered
    assert approved.id


def test_draft_detail_and_download(client, seller, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    draft = ListingDraft.objects.create(
        owner=seller,
        product_name="원피스",
        title="린넨 원피스 원피스",
        target_keywords=["린넨 원피스", "롱원피스"],
        category_path="패션의류 > 여성의류 > 원피스",
    )
    detail = client.get(f"/drafts/{draft.id}/").content.decode()
    assert "반복된 단어" in detail
    assert "아직 렌더링된" in detail
    assert client.get(f"/drafts/{draft.id}/download/").status_code == 404

    _render(draft, tmp_path)
    detail = client.get(f"/drafts/{draft.id}/").content.decode()
    assert "이미지 2장" in detail
    response = client.get(f"/drafts/{draft.id}/download/")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
    assert archive.namelist() == ["detail-01.jpg", "detail-02.jpg"]

    other = User.objects.create_user("other")
    client.force_login(other)
    assert client.get(f"/drafts/{draft.id}/download/").status_code == 404


def test_approve_draft(client, seller):
    draft = ListingDraft.objects.create(owner=seller, product_name="원피스")
    client.post(f"/drafts/{draft.id}/approve/")
    draft.refresh_from_db()
    assert draft.status == "approved"


# ---------------------------------------------------------- charts + filters
def test_monotone_path_never_overshoots():
    xs, ys = [0, 10, 20, 30], [50, 0, 0, 50]
    path = monotone_path(xs, ys)
    numbers = [float(v) for token in path.replace("M", " ").replace("C", " ").split() for v in token.split(",")]
    assert min(numbers[1::2]) >= 0  # control points stay within the data range


def test_area_chart_geometry():
    points = [{"period": f"2025-{m:02d}-01", "ratio": r} for m, r in enumerate([10, 40, 100, 30], start=1)]
    chart = area_chart(points)
    assert chart["peak"]["text"] == "3월"
    assert [label["text"] for label in chart["labels"]] == ["25년 1월", "2월", "3월", "4월"]
    assert chart["area"].endswith("Z")
    assert area_chart(points[:1]) is None


def test_price_positions():
    assert price_positions({"min": 100, "p25": 150, "median": 200, "p75": 250, "max": 300}) == {
        "p25": 25.0, "median": 50.0, "p75": 75.0, "iqr_width": 50.0,
    }
    assert price_positions({"min": 100, "max": 100}) is None


def test_ui_filters():
    assert compact(9999) == "9,999"
    assert compact(180000) == "18만"
    assert compact(123456789) == "1.2억"
    assert month_label("2025-07-01") == "2025년 7월"
    now = timezone.now()
    assert reltime(now) == "방금 전"
    assert reltime(now - timedelta(minutes=5)) == "5분 전"


# ---------------------------------------------------------------- rendering
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
def test_real_render_uses_bundled_font(seller, settings, monkeypatch):
    from PIL import Image

    from pivend.listings import renderer

    served = []
    original = renderer._serve_asset
    monkeypatch.setattr(renderer, "_serve_asset", lambda route: (served.append(route.request.url), original(route)))
    settings.PLAYWRIGHT_CHROMIUM_EXECUTABLE = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "")
    draft = ListingDraft.objects.create(owner=seller, product_name="원피스")
    render = renderer.render_detail_page(
        draft,
        {"sections": [{"type": "hero", "headline": "시원한 린넨 원피스"}, {"type": "faq", "items": [{"q": "세탁?", "a": "손세탁"}]}]},
    )
    first = Image.open(f"{settings.MEDIA_ROOT}/{render.images[0]}")
    assert first.width == 860
    assert render.height > 300
    assert served == [f"{renderer.FONT_HOST}{renderer.FONT_PATH}"]


def test_delete_redirect_ignores_foreign_referers(client, seller):
    keep = Conversation.objects.create(owner=seller, title="keep")
    gone = Conversation.objects.create(owner=seller, title="gone")
    response = client.post(f"/chat/{gone.id}/delete/", HTTP_REFERER=f"http://testserver/chat/{keep.id}/")
    assert response["Location"] == f"http://testserver/chat/{keep.id}/"
    other = Conversation.objects.create(owner=seller, title="other")
    response = client.post(f"/chat/{other.id}/delete/", HTTP_REFERER="https://evil.example/phish")
    assert response["Location"] == "/chat/"
