"""Per-user API credentials. Secrets are encrypted at rest (see crypto.py)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from . import crypto


class Credential(models.Model):
    class Kind(models.TextChoices):
        NAVER_SEARCHAD = "naver_searchad", "네이버 검색광고 API"
        NAVER_OPENAPI = "naver_openapi", "네이버 개발자센터 API"
        LLM = "llm", "AI 모델"

    class Status(models.TextChoices):
        UNTESTED = "untested", "테스트 전"
        OK = "ok", "연결됨"
        ERROR = "error", "오류"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credentials")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    # Non-secret settings (LLM provider, model, server URL...). Shown back in forms.
    config = models.JSONField(default=dict, blank=True)
    # Encrypted JSON of the secret values. Never rendered; only the hint is.
    secret_blob = models.TextField(blank=True)
    hint = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNTESTED)
    status_message = models.CharField(max_length=300, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "kind"], name="one_credential_per_kind")]

    def __str__(self):
        return f"{self.owner} · {self.get_kind_display()}"

    @property
    def secrets(self) -> dict:
        return crypto.decrypt(self.secret_blob)

    def set_secrets(self, values: dict) -> None:
        self.secret_blob = crypto.encrypt(values)
        self.hint = mask(next((v for v in values.values() if v), ""))

    def mark(self, ok: bool, message: str = "") -> None:
        from django.utils import timezone

        self.status = self.Status.OK if ok else self.Status.ERROR
        self.status_message = message[:300]
        self.checked_at = timezone.now()
        self.save(update_fields=["status", "status_message", "checked_at", "updated_at"])


def mask(value: str) -> str:
    value = str(value)
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"
