from django.conf import settings
from django.db import models


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
        """User and assistant text plus tool calls, for rendering history."""
        out = []
        for message in self.messages:
            role = message.get("role")
            content = message.get("content")
            if role == "user":
                text = content if isinstance(content, str) else "".join(
                    b.get("text", "") for b in content or [] if b.get("type") == "text"
                )
                out.append({"role": "user", "text": text})
            elif role == "assistant":
                text = "".join(b.get("text", "") for b in content or [] if b.get("type") == "text")
                tools = [b.get("name") for b in content or [] if b.get("type") == "toolCall"]
                if text:
                    out.append({"role": "assistant", "text": text})
                if tools:
                    out.append({"role": "tools", "names": tools})
                if message.get("stopReason") == "error" and message.get("errorMessage"):
                    out.append({"role": "error", "text": message["errorMessage"]})
        return out
