"""Reading, saving and testing a user's API connections.

Everything that needs a user's keys goes through here, so a platform-wide
fallback (keys the operator pays for) can be added in one place later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from django.conf import settings

from pivend.naver.errors import NaverError

from .crypto import SecretError
from .models import Credential
from .netguard import check_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    default_model: str
    needs_key: bool
    needs_url: bool
    key_url: str = ""
    note: str = ""


PROVIDERS = {
    p.key: p
    for p in [
        Provider("anthropic", "Claude (Anthropic)", "claude-opus-5", True, False, "https://console.anthropic.com/settings/keys"),
        Provider("openai", "OpenAI", "gpt-5.5", True, False, "https://platform.openai.com/api-keys"),
        Provider("google", "Gemini (Google)", "gemini-3.5-flash", True, False, "https://aistudio.google.com/apikey"),
        Provider(
            "llamacpp", "llama.cpp 서버", "", False, True,
            note="llama-server를 --jinja 옵션으로 실행하고, 이 서비스에서 접근할 수 있는 주소를 입력하세요.",
        ),
        Provider(
            "openai-compatible", "OpenAI 호환 서버", "", False, True,
            note="vLLM, LM Studio, Ollama, OpenRouter 등 /v1/chat/completions를 지원하는 서버.",
        ),
    ]
}

NAVER_FIELDS = {
    Credential.Kind.NAVER_SEARCHAD: ("api_key", "secret_key", "customer_id"),
    Credential.Kind.NAVER_OPENAPI: ("client_id", "client_secret"),
}


def get_credential(user, kind: str) -> Credential | None:
    return Credential.objects.filter(owner=user, kind=kind).first()


def credentials_by_kind(user) -> dict[str, Credential]:
    return {c.kind: c for c in Credential.objects.filter(owner=user)}


def _secrets(credential: Credential | None) -> dict:
    if credential is None:
        return {}
    try:
        return credential.secrets
    except SecretError:
        logger.error("Could not decrypt credential %s", credential.pk)
        return {}


def naver_keys(user, kind: str) -> dict | None:
    """The user's keys for one Naver API, or None if incomplete."""
    values = _secrets(get_credential(user, kind))
    fields = NAVER_FIELDS[kind]
    if not all(values.get(f) for f in fields):
        return None
    return {f: values[f] for f in fields}


def llm_config(user) -> dict | None:
    """What the agent service needs to run this user's model, key included."""
    credential = get_credential(user, Credential.Kind.LLM)
    if credential is None:
        return None
    config = dict(credential.config)
    provider = PROVIDERS.get(config.get("provider", ""))
    if provider is None:
        return None
    api_key = _secrets(credential).get("api_key", "")
    if provider.needs_key and not api_key:
        return None
    if provider.needs_url and not config.get("base_url"):
        return None
    return {
        "provider": provider.key,
        "model": config.get("model") or provider.default_model or None,
        "base_url": config.get("base_url") or None,
        "api_key": api_key or None,
        "reasoning": bool(config.get("reasoning")),
        "thinking_format": "qwen-chat-template" if config.get("reasoning") and provider.needs_url else None,
    }


def llm_label(user) -> dict | None:
    """Provider/model for display (no secrets)."""
    credential = get_credential(user, Credential.Kind.LLM)
    if credential is None:
        return None
    provider = PROVIDERS.get(credential.config.get("provider", ""))
    if provider is None:
        return None
    return {
        "provider": provider.key,
        "provider_label": provider.label,
        "model": credential.config.get("model") or provider.default_model or credential.config.get("detected_model") or "서버 기본 모델",
        "status": credential.status,
        "status_message": credential.status_message,
    }


# ------------------------------------------------------------------- saving
class CredentialError(ValueError):
    pass


def save_naver(user, kind: str, values: dict[str, str]) -> Credential:
    """Save Naver keys. Blank fields keep the stored value, so users don't
    have to re-enter secrets to change one of them."""
    fields = NAVER_FIELDS[kind]
    credential = get_credential(user, kind) or Credential(owner=user, kind=kind)
    current = _secrets(credential) if credential.pk else {}
    merged = {f: (values.get(f) or "").strip() or current.get(f, "") for f in fields}
    missing = [f for f in fields if not merged[f]]
    if missing:
        raise CredentialError("모든 항목을 입력해 주세요.")
    credential.set_secrets(merged)
    if kind == Credential.Kind.NAVER_SEARCHAD:
        credential.hint = f"고객 ID {merged['customer_id']}"
    credential.status, credential.status_message, credential.checked_at = Credential.Status.UNTESTED, "", None
    credential.save()
    return credential


def save_llm(user, provider_key: str, model: str, base_url: str, api_key: str, reasoning: bool) -> Credential:
    provider = PROVIDERS.get(provider_key)
    if provider is None:
        raise CredentialError("AI 모델 제공자를 선택해 주세요.")
    credential = get_credential(user, Credential.Kind.LLM) or Credential(owner=user, kind=Credential.Kind.LLM)
    previous = credential.config if credential.pk else {}
    same_provider = previous.get("provider") == provider.key
    current_key = _secrets(credential).get("api_key", "") if credential.pk and same_provider else ""
    api_key = api_key.strip() or current_key
    base_url = base_url.strip().rstrip("/")
    if provider.needs_key and not api_key:
        raise CredentialError(f"{provider.label} API 키를 입력해 주세요.")
    if provider.needs_url:
        if not base_url:
            raise CredentialError("서버 주소를 입력해 주세요. 예: https://llm.example.com/v1")
        problem = check_url(base_url, allow_private=settings.ALLOW_PRIVATE_LLM_URLS)
        if problem:
            raise CredentialError(problem)
    else:
        base_url = ""
    credential.config = {
        "provider": provider.key,
        "model": model.strip()[:100],
        "base_url": base_url,
        "reasoning": bool(reasoning) and provider.needs_url,
    }
    credential.set_secrets({"api_key": api_key})
    if not api_key:
        credential.hint = ""
    credential.status, credential.status_message, credential.checked_at = Credential.Status.UNTESTED, "", None
    credential.save()
    return credential


def delete_credential(user, kind: str) -> None:
    Credential.objects.filter(owner=user, kind=kind).delete()


# ------------------------------------------------------------------ testing
def _naver_message(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "키가 올바르지 않거나 이 API 사용 권한이 없어요."
    if status == 429:
        return "호출 한도를 초과했어요. 잠시 후 다시 시도해 주세요."
    return f"네이버 API 오류: {exc}"


def check_credential(user, kind: str) -> Credential:
    """Make a small real call with the stored keys and record the result."""
    credential = get_credential(user, kind)
    if credential is None:
        raise CredentialError("먼저 키를 저장해 주세요.")
    try:
        if kind == Credential.Kind.NAVER_SEARCHAD:
            ok, message = _test_searchad(user)
        elif kind == Credential.Kind.NAVER_OPENAPI:
            ok, message = _test_openapi(user)
        else:
            ok, message = _test_llm(user)
    except NaverError as exc:
        ok, message = False, _naver_message(exc)
    credential.mark(ok, message)
    return credential


def _test_searchad(user) -> tuple[bool, str]:
    from pivend.naver.searchad import SearchAdClient

    keys = naver_keys(user, Credential.Kind.NAVER_SEARCHAD)
    if keys is None:
        return False, "저장된 키가 완전하지 않아요."
    rows = SearchAdClient(keys["api_key"], keys["secret_key"], keys["customer_id"]).keywordstool(["원피스"])
    return True, f"키워드도구 응답 확인 (연관 키워드 {len(rows):,}개)"


def _test_openapi(user) -> tuple[bool, str]:
    from datetime import date, timedelta

    from pivend.naver.openapi import NaverOpenAPIClient

    keys = naver_keys(user, Credential.Kind.NAVER_OPENAPI)
    if keys is None:
        return False, "저장된 키가 완전하지 않아요."
    client = NaverOpenAPIClient(keys["client_id"], keys["client_secret"])
    client.shopping_search("원피스", display=1)
    end = date.today() - timedelta(days=1)
    try:
        client.search_trend({"원피스": ["원피스"]}, (end - timedelta(days=30)).isoformat(), end.isoformat(), "week")
    except NaverError as exc:
        return False, "쇼핑 검색은 되지만 데이터랩 권한이 없어요. 애플리케이션 API 설정에 '데이터랩(검색어트렌드)'과 '데이터랩(쇼핑인사이트)'를 추가해 주세요." if getattr(exc, "status_code", None) in (401, 403) else _naver_message(exc)
    return True, "쇼핑 검색과 데이터랩 응답 확인"


def _test_llm(user) -> tuple[bool, str]:
    config = llm_config(user)
    if config is None:
        return False, "설정이 완전하지 않아요."
    try:
        response = httpx.post(
            f"{settings.AGENT_URL}/v1/test",
            json={"llm": config},
            headers={"Authorization": f"Bearer {settings.AGENT_INTERNAL_TOKEN}"},
            timeout=httpx.Timeout(10.0, read=90.0),
        )
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return False, f"에이전트 서비스에 연결할 수 없어요 ({exc.__class__.__name__})."
    if response.status_code != 200 or not data.get("ok"):
        return False, str(data.get("error") or f"HTTP {response.status_code}")[:300]
    credential = get_credential(user, Credential.Kind.LLM)
    if credential and not credential.config.get("model") and data.get("model"):
        # Local servers pick the model; remember which one for display.
        credential.config = {**credential.config, "detected_model": str(data["model"])[:100]}
        credential.save(update_fields=["config", "updated_at"])
    return True, f"{data.get('model') or config['model']} 응답 확인"


def agent_catalog() -> dict[str, list[str]]:
    """Model ids the agent service knows for each cloud provider (for suggestions)."""
    from django.core.cache import cache

    catalog = cache.get("agent_model_catalog")
    if catalog is not None:
        return catalog
    try:
        response = httpx.get(
            f"{settings.AGENT_URL}/v1/models",
            headers={"Authorization": f"Bearer {settings.AGENT_INTERNAL_TOKEN}"},
            timeout=3.0,
        )
        response.raise_for_status()
        catalog = response.json().get("providers", {})
        cache.set("agent_model_catalog", catalog, 3600)
    except (httpx.HTTPError, ValueError):
        catalog = {}
        cache.set("agent_model_catalog", catalog, 30)
    return catalog
