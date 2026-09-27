"""Browser-facing chat endpoints. Django owns auth and conversation storage;
the Node agent service is stateless and only reachable from here."""

from __future__ import annotations

import json
import logging

import httpx
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from .models import Conversation

logger = logging.getLogger(__name__)

SUGGESTIONS = [
    {
        "icon": "scan-search",
        "title": "롱테일 키워드 발굴",
        "desc": "검색량은 충분하고 경쟁은 덜한 키워드 찾기",
        "prompt": "여름 린넨 원피스를 팔려고 해요. 검색량 대비 경쟁이 낮은 롱테일 키워드를 찾아주세요.",
        "mode": "send",
    },
    {
        "icon": "type",
        "title": "상품명 최적화",
        "desc": "지금 상품명을 점검하고 더 나은 안 제안",
        "prompt": "지금 상품명을 네이버 스마트스토어 기준으로 점검하고 더 나은 상품명 3개를 제안해 주세요.\n현재 상품명: ",
        "mode": "fill",
    },
    {
        "icon": "image",
        "title": "상세페이지 만들기",
        "desc": "제품 정보로 모바일 상세페이지 생성",
        "prompt": "상세페이지를 만들어 주세요.\n- 상품: \n- 소재/스펙: \n- 가격대: \n- 타깃 고객: \n- 강조하고 싶은 점: ",
        "mode": "fill",
    },
    {
        "icon": "trending-up",
        "title": "시즌 트렌드",
        "desc": "검색 흐름으로 판매·광고 타이밍 잡기",
        "prompt": "캠핑의자와 캠핑테이블의 최근 1년 검색 트렌드를 비교하고, 언제 광고를 늘리면 좋을지 알려주세요.",
        "mode": "send",
    },
]


def _agent_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.AGENT_INTERNAL_TOKEN}"}


def agent_health() -> dict:
    try:
        response = httpx.get(f"{settings.AGENT_URL}/health", headers=_agent_headers(), timeout=2.0)
        response.raise_for_status()
        return {"online": True, **response.json()}
    except (httpx.HTTPError, ValueError) as exc:
        return {"online": False, "error": str(exc)}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@login_required
@xframe_options_sameorigin
def chat(request, conversation_id: int | None = None):
    current = None
    if conversation_id is not None:
        current = get_object_or_404(Conversation, owner=request.user, id=conversation_id)
    return render(
        request,
        "assistant/chat.html",
        {
            "current": current,
            "history": current.display_messages() if current else [],
            "suggestions": SUGGESTIONS,
            "prefill": request.GET.get("prompt", "")[:2000],
            "embed": request.GET.get("embed") == "1",
        },
    )


@login_required
@require_POST
def new_conversation(request):
    """Created lazily by the chat page on the first message, so empty chats never pile up."""
    conversation = Conversation.objects.create(owner=request.user)
    return JsonResponse(
        {
            "id": conversation.id,
            "url": reverse("chat_conversation", args=[conversation.id]),
            "send_url": reverse("chat_send", args=[conversation.id]),
        }
    )


@login_required
@require_POST
def delete_conversation(request, conversation_id: int):
    get_object_or_404(Conversation, owner=request.user, id=conversation_id).delete()
    referer = request.META.get("HTTP_REFERER", "")
    same_site = url_has_allowed_host_and_scheme(referer, {request.get_host()}, request.is_secure())
    if not same_site or referer.rstrip("/").endswith(f"/chat/{conversation_id}"):
        return redirect("chat")
    return redirect(referer)


@login_required
@require_POST
def send_message(request, conversation_id: int):
    conversation = get_object_or_404(Conversation, owner=request.user, id=conversation_id)
    try:
        text = str(json.loads(request.body).get("message", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        return HttpResponseBadRequest("invalid JSON")
    if not text:
        return HttpResponseBadRequest("message is required")
    if not conversation.title:
        conversation.title = " ".join(text.split())[:60]
        conversation.save(update_fields=["title", "updated_at"])

    payload = {
        "user_id": request.user.id,
        "conversation_id": conversation.id,
        "messages": conversation.messages,
        "message": text,
    }

    def stream():
        try:
            with httpx.stream(
                "POST",
                f"{settings.AGENT_URL}/v1/chat",
                json=payload,
                headers=_agent_headers(),
                timeout=httpx.Timeout(10.0, read=600.0),
            ) as response:
                if response.status_code != 200:
                    response.read()
                    yield _sse({"type": "error", "message": f"Agent error {response.status_code}: {response.text[:300]}"})
                    return
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "done":
                        # The transcript stays server-side; the browser only needs usage.
                        conversation.messages = event.get("messages", conversation.messages)
                        conversation.save(update_fields=["messages", "updated_at"])
                        yield _sse({"type": "done", "usage": event.get("usage")})
                    else:
                        yield line + "\n\n"
        except httpx.HTTPError as exc:
            logger.warning("Agent stream failed: %s", exc)
            yield _sse({"type": "error", "message": f"에이전트에 연결할 수 없어요 ({exc})"})

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def health(request):
    return JsonResponse(agent_health())
