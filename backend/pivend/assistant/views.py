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
from django.views.decorators.http import require_POST

from .models import Conversation

logger = logging.getLogger(__name__)


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
def chat(request, conversation_id: int | None = None):
    conversations = Conversation.objects.filter(owner=request.user)[:50]
    current = None
    if conversation_id is not None:
        current = get_object_or_404(Conversation, owner=request.user, id=conversation_id)
    return render(
        request,
        "assistant/chat.html",
        {"conversations": conversations, "current": current, "agent": agent_health()},
    )


@login_required
@require_POST
def new_conversation(request):
    conversation = Conversation.objects.create(owner=request.user)
    return redirect("chat_conversation", conversation_id=conversation.id)


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
        conversation.title = text[:60]
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
            yield _sse({"type": "error", "message": f"Agent unavailable: {exc}"})

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def health(request):
    return JsonResponse(agent_health())
