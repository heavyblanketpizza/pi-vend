import json
import re
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core import mail

from pivend.accounts import crypto
from pivend.accounts.models import Credential
from pivend.accounts.netguard import check_url
from pivend.accounts.services import CredentialError, check_credential, llm_config, save_llm, save_naver

from .conftest import connect_llm, connect_naver


@pytest.fixture
def seller(client, db):
    user = User.objects.create_user("seller@example.com", email="seller@example.com", password="pw-long-enough-1")
    client.force_login(user)
    return user


# ------------------------------------------------------------------ secrets
def test_secrets_are_encrypted_at_rest(seller):
    connect_naver(seller)
    credential = Credential.objects.get(owner=seller, kind=Credential.Kind.NAVER_OPENAPI)
    assert "csecret" not in credential.secret_blob and "cid" not in credential.secret_blob
    assert credential.secrets == {"client_id": "cid", "client_secret": "csecret"}
    assert credential.hint == "••••"  # short values are fully masked


def test_key_rotation(seller, settings):
    connect_naver(seller)
    old_key = settings.CREDENTIAL_ENCRYPTION_KEYS[0]
    settings.CREDENTIAL_ENCRYPTION_KEYS = [Fernet.generate_key().decode(), old_key]
    from django.core.management import call_command

    call_command("rotate_credentials")
    settings.CREDENTIAL_ENCRYPTION_KEYS = settings.CREDENTIAL_ENCRYPTION_KEYS[:1]  # old key retired
    assert Credential.objects.get(owner=seller, kind=Credential.Kind.NAVER_OPENAPI).secrets["client_secret"] == "csecret"

    settings.CREDENTIAL_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]
    with pytest.raises(crypto.SecretError):
        Credential.objects.get(owner=seller, kind=Credential.Kind.NAVER_OPENAPI).secrets


def test_blank_fields_keep_saved_secrets(seller):
    connect_naver(seller)
    save_naver(seller, Credential.Kind.NAVER_SEARCHAD, {"api_key": "", "secret_key": "new-secret", "customer_id": ""})
    secrets = Credential.objects.get(owner=seller, kind=Credential.Kind.NAVER_SEARCHAD).secrets
    assert secrets == {"api_key": "ak", "secret_key": "new-secret", "customer_id": "1234567"}
    with pytest.raises(CredentialError):
        save_naver(User.objects.create_user("x"), Credential.Kind.NAVER_OPENAPI, {"client_id": "only-id"})


def test_llm_settings_validation(seller):
    with pytest.raises(CredentialError, match="API 키"):
        save_llm(seller, "openai", "", "", "", False)
    with pytest.raises(CredentialError, match="서버 주소"):
        save_llm(seller, "llamacpp", "", "", "", False)
    with pytest.raises(CredentialError, match="공개 주소"):
        save_llm(seller, "llamacpp", "", "http://127.0.0.1:8080/v1", "", False)
    with pytest.raises(CredentialError, match="공개 주소"):
        save_llm(seller, "openai-compatible", "", "http://169.254.169.254/latest", "", False)

    save_llm(seller, "llamacpp", "", "http://8.8.8.8:8080/v1/", "", True)
    assert llm_config(seller) == {
        "provider": "llamacpp", "model": None, "base_url": "http://8.8.8.8:8080/v1", "api_key": None,
        "reasoning": True, "thinking_format": "qwen-chat-template",
    }

    # Switching provider never reuses the previous provider's key.
    save_llm(seller, "openai", "gpt-5.5", "", "sk-openai-123456789", False)
    with pytest.raises(CredentialError):
        save_llm(seller, "anthropic", "", "", "", False)
    # Same provider: blank key keeps the saved one.
    save_llm(seller, "openai", "gpt-5.4", "", "", False)
    assert llm_config(seller)["api_key"] == "sk-openai-123456789"
    assert Credential.objects.get(owner=seller, kind="llm").hint == "••••6789"


def test_private_llm_urls_allowed_only_when_configured(seller, settings):
    settings.ALLOW_PRIVATE_LLM_URLS = True
    save_llm(seller, "llamacpp", "", "http://llamacpp:8080/v1", "", False)
    assert llm_config(seller)["base_url"] == "http://llamacpp:8080/v1"


@pytest.mark.parametrize(
    "url,ok",
    [("https://8.8.8.8/v1", True), ("http://localhost:8080", False), ("http://10.0.0.1", False),
     ("ftp://8.8.8.8", False), ("http://user:pw@8.8.8.8/v1", False), ("not a url", False)],
)
def test_check_url(url, ok):
    assert (check_url(url) is None) is ok


# ------------------------------------------------------------- connection tests
@respx.mock
def test_connection_checks_record_status(seller):
    connect_naver(seller)
    connect_llm(seller)
    respx.get("https://api.searchad.naver.com/keywordstool").mock(
        return_value=httpx.Response(200, json={"keywordList": [{"relKeyword": "원피스", "monthlyPcQcCnt": 10, "monthlyMobileQcCnt": 20}]})
    )
    respx.get(url__startswith="https://openapi.naver.com/v1/search/shop.json").mock(
        return_value=httpx.Response(200, json={"total": 5, "items": []})
    )
    respx.post("https://openapi.naver.com/v1/datalab/search").mock(return_value=httpx.Response(403, json={"errorMessage": "no"}))
    agent = respx.post("http://agent.test/v1/test").mock(return_value=httpx.Response(200, json={"ok": True, "model": "claude-opus-5"}))

    assert check_credential(seller, Credential.Kind.NAVER_SEARCHAD).status == "ok"
    openapi = check_credential(seller, Credential.Kind.NAVER_OPENAPI)
    assert openapi.status == "error" and "데이터랩" in openapi.status_message
    assert check_credential(seller, Credential.Kind.LLM).status == "ok"
    assert json.loads(agent.calls.last.request.content)["llm"]["api_key"] == "sk-ant-user"

    respx.get("https://api.searchad.naver.com/keywordstool").mock(return_value=httpx.Response(401, text="unauthorized"))
    failed = check_credential(seller, Credential.Kind.NAVER_SEARCHAD)
    assert failed.status == "error" and "올바르지" in failed.status_message


@respx.mock
def test_connections_page_saves_tests_and_never_shows_secrets(client, seller):
    respx.post("http://agent.test/v1/test").mock(return_value=httpx.Response(200, json={"ok": False, "error": "invalid x-api-key"}))
    respx.get("http://agent.test/v1/models").mock(return_value=httpx.Response(200, json={"providers": {"anthropic": ["claude-opus-5"]}}))

    page = client.get("/settings/?welcome=1").content.decode()
    assert "가입을 환영해요" in page and "0/4 완료" in page

    response = client.post(
        "/settings/connections/llm/save/",
        {"provider": "anthropic", "model": "", "api_key": "sk-ant-api03-secret-value-9876"},
        follow=True,
    )
    page = response.content.decode()
    assert "AI 모델 연결 실패: invalid x-api-key" in page
    assert "sk-ant-api03-secret-value-9876" not in page and "••••9876" in page
    assert '<option value="claude-opus-5">' in page

    client.post("/settings/connections/llm/delete/")
    assert not Credential.objects.filter(owner=seller).exists()
    assert client.post("/settings/connections/nope/save/").status_code == 404


# ------------------------------------------------------------------ sign-up
def _link(message) -> str:
    return re.search(r"https?://\S+", message.body).group(0).replace("http://testserver", "")


def test_signup_verify_and_login(client, db):
    response = client.post("/signup/", {"email": "New@Example.com", "password": "linen-dress-2026"})
    assert response.status_code == 302 and response["Location"] == "/signup/sent/"
    user = User.objects.get(email="new@example.com")
    assert not user.is_active and user.username == "new@example.com"
    assert len(mail.outbox) == 1 and "인증" in mail.outbox[0].subject

    page = client.post("/login/", {"username": "new@example.com", "password": "linen-dress-2026"}).content.decode()
    assert "이메일 인증이 아직 끝나지 않았어요" in page and "인증 메일 다시 받기" in page

    link = _link(mail.outbox[0])
    response = client.get(link)
    assert response.status_code == 302 and response["Location"] == "/settings/?welcome=1"
    user.refresh_from_db()
    assert user.is_active

    client.logout()
    assert client.get(link).status_code == 400  # one-time link

    response = client.post("/login/", {"username": "NEW@example.com", "password": "linen-dress-2026"})
    assert response.status_code == 302


def test_signup_rejections(client, db, settings):
    User.objects.create_user("taken@example.com", email="taken@example.com", password="x")
    page = client.post("/signup/", {"email": "taken@example.com", "password": "linen-dress-2026"}).content.decode()
    assert "이미 가입된 이메일" in page
    page = client.post("/signup/", {"email": "a@example.com", "password": "12345678"}).content.decode()
    assert "field-error" in page and not User.objects.filter(email="a@example.com").exists()

    # Honeypot: looks like success, creates nothing.
    response = client.post("/signup/", {"email": "bot@example.com", "password": "linen-dress-2026", "website": "spam"})
    assert response["Location"] == "/signup/sent/" and not User.objects.filter(email="bot@example.com").exists()

    settings.SIGNUPS_OPEN = False
    assert client.get("/signup/").status_code == 403
    assert "무료로 가입하기" not in client.get("/login/").content.decode()


def test_signup_without_verification_logs_in(client, db, settings):
    settings.EMAIL_VERIFICATION = False
    response = client.post("/signup/", {"email": "fast@example.com", "password": "linen-dress-2026"})
    assert response["Location"] == "/settings/?welcome=1"
    assert client.get("/settings/").status_code == 200
    assert mail.outbox == []


def test_signup_rate_limit(client, db, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "signup": (1, 3600)}
    client.post("/signup/", {"email": "one@example.com", "password": "linen-dress-2026"})
    page = client.post("/signup/", {"email": "two@example.com", "password": "linen-dress-2026"}).content.decode()
    assert "너무 많아요" in page and not User.objects.filter(email="two@example.com").exists()


def test_password_reset(client, db):
    User.objects.create_user("r@example.com", email="r@example.com", password="old-password-11")
    client.post("/password/reset/", {"email": "R@example.com"})
    assert len(mail.outbox) == 1 and "비밀번호 재설정" in mail.outbox[0].subject
    response = client.get(_link(mail.outbox[0]), follow=True)
    form_url = response.redirect_chain[-1][0]
    client.post(form_url, {"new_password1": "new-password-22", "new_password2": "new-password-22"})
    assert client.login(username="r@example.com", password="new-password-22")

    client.logout()
    client.post("/password/reset/", {"email": "nobody@example.com"})
    assert len(mail.outbox) == 1  # nothing sent, same response


def test_change_password_and_delete_account(client, seller, settings, tmp_path):
    from pivend.listings.models import DetailPageRender, ListingDraft
    from pivend.store.demo import create_demo

    page = client.post("/settings/account/", {
        "action": "password", "old_password": "pw-long-enough-1",
        "new_password1": "linen-dress-2027", "new_password2": "linen-dress-2027",
    }, follow=True).content.decode()
    assert "비밀번호를 바꿨어요" in page

    settings.MEDIA_ROOT = str(tmp_path)
    draft = ListingDraft.objects.create(owner=seller, product_name="원피스")
    image = tmp_path / "detail-pages" / str(draft.id) / "r-abc" / "01.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"jpg")
    DetailPageRender.objects.create(draft=draft, spec={}, html="", images=[f"detail-pages/{draft.id}/r-abc/01.jpg"])
    create_demo(seller, days=30)
    connect_naver(seller)

    page = client.post("/settings/account/", {"action": "delete", "password": "wrong"}).content.decode()
    assert "비밀번호가 올바르지 않아요" in page
    client.post("/settings/account/", {"action": "delete", "password": "linen-dress-2027"})
    assert not User.objects.filter(id=seller.id).exists()
    assert not Credential.objects.exists() and not ListingDraft.objects.exists()
    assert not image.exists() and not Path(image.parent).exists()


# ------------------------------------------------------------------ limits
def test_chat_rate_limit(client, seller, settings):
    from pivend.assistant.models import Conversation

    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "chat": (0, 3600)}
    connect_llm(seller)
    conversation = Conversation.objects.create(owner=seller)
    response = client.post(f"/chat/{conversation.id}/send/", data=json.dumps({"message": "hi"}), content_type="application/json")
    assert '"rate_limited"' in b"".join(response.streaming_content).decode()
