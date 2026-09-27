import json

from django.conf import settings
from django.db import models


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


class Conversation(models.Model):
    """A chat with the agent. `messages` is the Pi agent transcript
    (user / assistant / toolResult messages, without the system prompt)."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=120, blank=True)
    messages = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Conversation {self.pk}"

    def display_messages(self) -> list[dict]:
        """The transcript reduced to what the chat UI draws: user text,
        assistant text, tool steps (with outcome and rendered images) and errors."""
        results = {
            m.get("toolCallId"): m for m in self.messages if isinstance(m, dict) and m.get("role") == "toolResult"
        }
        out: list[dict] = []
        for message in self.messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "user":
                out.append({"role": "user", "text": _text(message.get("content"))})
            elif role == "assistant":
                content = message.get("content") or []
                text = _text(content)
                if text:
                    out.append({"role": "assistant", "text": text})
                steps = [
                    self._step(block, results.get(block.get("id")))
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "toolCall"
                ]
                if steps:
                    out.append({"role": "tools", "steps": steps})
                if message.get("stopReason") == "error" and message.get("errorMessage"):
                    out.append({"role": "error", "text": message["errorMessage"]})
        return out

    @staticmethod
    def _step(call: dict, result: dict | None) -> dict:
        step = {"name": call.get("name"), "args": call.get("arguments") or {}, "isError": False}
        if result is None:
            return step
        step["isError"] = bool(result.get("isError"))
        text = _text(result.get("content"))
        if step["isError"]:
            step["summary"] = text[:300]
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        if not details and text.startswith("{"):
            try:
                parsed = json.loads(text)
                details = {"images": parsed.get("images"), "url": parsed.get("draft_url") or parsed.get("url")}
            except (ValueError, AttributeError):
                details = {}
        if isinstance(details.get("images"), list):
            step["images"] = details["images"]
        if isinstance(details.get("url"), str):
            step["draftUrl"] = details["url"]
        return step
