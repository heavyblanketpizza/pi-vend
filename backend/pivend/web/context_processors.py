"""Data every app-shell page needs: recent conversations, draft count, agent status."""

from django.core.cache import cache
from django.utils import timezone

from pivend.assistant.models import Conversation
from pivend.assistant.views import agent_health
from pivend.listings.models import ListingDraft

AGENT_STATUS_TTL = 20  # seconds


def cached_agent_health() -> dict:
    status = cache.get("agent_health")
    if status is None:
        status = agent_health()
        cache.set("agent_health", status, AGENT_STATUS_TTL if status.get("online") else 5)
    return status


def _group_conversations(conversations) -> list[tuple[str, list]]:
    today = timezone.localdate()
    buckets: dict[str, list] = {"오늘": [], "어제": [], "지난 7일": [], "이전": []}
    for c in conversations:
        days = (today - timezone.localtime(c.updated_at).date()).days
        key = "오늘" if days <= 0 else "어제" if days == 1 else "지난 7일" if days < 7 else "이전"
        buckets[key].append(c)
    return [(label, items) for label, items in buckets.items() if items]


def shell(request):
    if not request.user.is_authenticated or request.path.startswith(("/internal/", "/admin/")):
        return {}
    conversations = (
        Conversation.objects.filter(owner=request.user)
        .exclude(title="")
        .only("id", "title", "updated_at")[:40]
    )
    return {
        "shell_conversations": _group_conversations(conversations),
        "shell_draft_count": ListingDraft.objects.filter(owner=request.user).count(),
        "agent": cached_agent_health(),
    }
