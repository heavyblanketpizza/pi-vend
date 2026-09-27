from __future__ import annotations

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.http import Http404
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from . import ratelimit, services
from .forms import DeleteAccountForm, LoginForm, ResetForm, SignupForm
from .models import Credential

logger = logging.getLogger(__name__)
User = get_user_model()
BACKEND = "pivend.accounts.backends.EmailBackend"


def _absolute(request, path: str) -> str:
    return request.build_absolute_uri(path)


def send_verification(request, user) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = _absolute(request, reverse("verify_email", args=[uid, token]))
    body = render_to_string("accounts/email/verify.txt", {"link": link, "user": user})
    send_mail("[Pi-Vend] 이메일 주소를 인증해 주세요", body, None, [user.email])


# ------------------------------------------------------------------ sign-up
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if not settings.SIGNUPS_OPEN:
        return render(request, "accounts/signup_closed.html", status=403)
    form = SignupForm(request.POST or None)
    if request.method == "POST":
        if not ratelimit.hit("signup", ratelimit.client_ip(request)):
            form.add_error(None, "가입 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
        elif form.is_valid() and not form.is_bot():
            user = form.save(active=not settings.EMAIL_VERIFICATION)
            if settings.EMAIL_VERIFICATION:
                send_verification(request, user)
                request.session["pending_email"] = user.email
                return redirect("signup_sent")
            login(request, user, backend=BACKEND)
            return redirect(f"{reverse('connections')}?welcome=1")
        elif form.is_bot():
            return redirect("signup_sent")
    return render(request, "accounts/signup.html", {"form": form})


def signup_sent(request):
    return render(request, "accounts/signup_sent.html", {"email": request.session.get("pending_email", "")})


@require_POST
def resend_verification(request):
    email = request.POST.get("email", "").strip()
    ip = ratelimit.client_ip(request)
    if email and ratelimit.hit("email", ip) and ratelimit.hit("email", email.lower()):
        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user is not None:
            send_verification(request, user)
    # Same answer whether or not the address exists.
    request.session["pending_email"] = email
    messages.success(request, "인증 메일을 다시 보냈어요. 몇 분 안에 도착하지 않으면 스팸함도 확인해 주세요.")
    return redirect("signup_sent")


def verify_email(request, uidb64: str, token: str):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None
    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "accounts/verify_invalid.html", status=400)
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])
    login(request, user, backend=BACKEND)  # also invalidates the link (last_login changes)
    request.session.pop("pending_email", None)
    return redirect(f"{reverse('connections')}?welcome=1")


# ------------------------------------------------------------------- log in
class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "signups_open": settings.SIGNUPS_OPEN}

    def form_invalid(self, form):
        response = super().form_invalid(form)
        response.context_data["unverified_email"] = getattr(form, "unverified_email", "")
        return response


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = ResetForm
    email_template_name = "accounts/email/password_reset.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        ip = ratelimit.client_ip(self.request)
        email = form.cleaned_data["email"].lower()
        if not (ratelimit.hit("email", ip) and ratelimit.hit("email", email)):
            return redirect(self.success_url)  # quietly drop floods; same page either way
        return super().form_valid(form)


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("login")
    post_reset_login = False

    def form_valid(self, form):
        messages.success(self.request, "비밀번호를 바꿨어요. 새 비밀번호로 로그인해 주세요.")
        return super().form_valid(form)


# ----------------------------------------------------------------- settings
KIND_SLUGS = {
    "llm": Credential.Kind.LLM,
    "searchad": Credential.Kind.NAVER_SEARCHAD,
    "openapi": Credential.Kind.NAVER_OPENAPI,
}


def setup_steps(user) -> list[dict]:
    """First-run checklist shown on the settings and dashboard pages."""
    from pivend.store.models import Store

    creds = services.credentials_by_kind(user)

    def working(kind) -> bool:
        credential = creds.get(kind)
        return credential is not None and credential.status == Credential.Status.OK

    return [
        {
            "key": "llm", "title": "AI 모델 연결", "desc": "Claude·OpenAI·Gemini 키 또는 내 LLM 서버",
            "done": working(Credential.Kind.LLM), "url": reverse("connections") + "#llm",
        },
        {
            "key": "searchad", "title": "검색광고 API", "desc": "월간 검색량·연관 키워드",
            "done": working(Credential.Kind.NAVER_SEARCHAD), "url": reverse("connections") + "#searchad",
        },
        {
            "key": "openapi", "title": "개발자센터 API", "desc": "상품 수·경쟁 상품·트렌드",
            "done": working(Credential.Kind.NAVER_OPENAPI), "url": reverse("connections") + "#openapi",
        },
        {
            "key": "data", "title": "스토어 데이터", "desc": "리포트 업로드 또는 데모 데이터",
            "done": Store.objects.filter(owner=user).exists(), "url": reverse("data_sources"),
        },
    ]


@login_required
def connections(request):
    creds = services.credentials_by_kind(request.user)
    llm = creds.get(Credential.Kind.LLM)
    steps = setup_steps(request.user)
    return render(
        request,
        "accounts/connections.html",
        {
            "section": "connections",
            "welcome": request.GET.get("welcome") == "1",
            "steps": steps,
            "steps_done": sum(s["done"] for s in steps),
            "llm": llm,
            "llm_config": llm.config if llm else {},
            "searchad": creds.get(Credential.Kind.NAVER_SEARCHAD),
            "openapi": creds.get(Credential.Kind.NAVER_OPENAPI),
            "providers": list(services.PROVIDERS.values()),
            "catalog": services.agent_catalog(),
            "allow_private": settings.ALLOW_PRIVATE_LLM_URLS,
        },
    )


def _run_check(request, kind: str) -> None:
    if not ratelimit.hit("credential_test", request.user.pk):
        messages.error(request, "연결 테스트를 너무 자주 했어요. 잠시 후 다시 시도해 주세요.")
        return
    credential = services.check_credential(request.user, kind)
    if credential.status == Credential.Status.OK:
        messages.success(request, f"{credential.get_kind_display()} 연결 확인: {credential.status_message}")
    else:
        messages.error(request, f"{credential.get_kind_display()} 연결 실패: {credential.status_message}")


@login_required
@require_POST
def save_connection(request, slug: str):
    kind = KIND_SLUGS.get(slug)
    if kind is None:
        raise Http404
    post = request.POST
    try:
        if kind == Credential.Kind.LLM:
            services.save_llm(
                request.user,
                provider_key=post.get("provider", ""),
                model=post.get("model", ""),
                base_url=post.get("base_url", ""),
                api_key=post.get("api_key", ""),
                reasoning=post.get("reasoning") == "on",
            )
        else:
            services.save_naver(request.user, kind, {f: post.get(f, "") for f in services.NAVER_FIELDS[kind]})
    except services.CredentialError as exc:
        messages.error(request, str(exc))
        return redirect(f"{reverse('connections')}#{slug}")
    _run_check(request, kind)  # save & test in one step
    return redirect(f"{reverse('connections')}#{slug}")


@login_required
@require_POST
def test_connection(request, slug: str):
    kind = KIND_SLUGS.get(slug)
    if kind is None:
        raise Http404
    try:
        _run_check(request, kind)
    except services.CredentialError as exc:
        messages.error(request, str(exc))
    return redirect(f"{reverse('connections')}#{slug}")


@login_required
@require_POST
def delete_connection(request, slug: str):
    kind = KIND_SLUGS.get(slug)
    if kind is None:
        raise Http404
    services.delete_credential(request.user, kind)
    messages.success(request, "연결을 삭제했어요. 저장된 키도 함께 지웠어요.")
    return redirect(f"{reverse('connections')}#{slug}")


@login_required
def account(request):
    password_form = PasswordChangeForm(request.user)
    delete_form = DeleteAccountForm(request.user)
    if request.method == "POST" and request.POST.get("action") == "password":
        password_form = PasswordChangeForm(request.user, request.POST)
        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "비밀번호를 바꿨어요.")
            return redirect("account")
    elif request.method == "POST" and request.POST.get("action") == "delete":
        delete_form = DeleteAccountForm(request.user, request.POST)
        if delete_form.is_valid():
            user = request.user
            logout(request)
            user.delete()  # cascades to stores, drafts (and their images), conversations and keys
            messages.success(request, "계정과 모든 데이터를 삭제했어요.")
            return redirect("login")
    return render(
        request,
        "accounts/account.html",
        {"section": "account", "password_form": password_form, "delete_form": delete_form},
    )
