from __future__ import annotations

from django import forms
from django.contrib.auth import authenticate, get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm

User = get_user_model()


class SignupForm(forms.Form):
    email = forms.EmailField(label="이메일", max_length=150)
    password = forms.CharField(label="비밀번호", widget=forms.PasswordInput, strip=False)
    # Bots fill every field; people never see this one.
    website = forms.CharField(required=False)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("이미 가입된 이메일이에요. 로그인하거나 비밀번호를 재설정해 주세요.")
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password:
            user = User(username=cleaned.get("email", ""), email=cleaned.get("email", ""))
            try:
                password_validation.validate_password(password, user)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return cleaned

    def is_bot(self) -> bool:
        return bool(self.data.get("website"))

    def save(self, active: bool):
        email = self.cleaned_data["email"]
        user = User(username=email, email=email, is_active=active)
        user.set_password(self.cleaned_data["password"])
        user.save()
        return user


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "이메일 또는 비밀번호가 올바르지 않아요.",
        "inactive": "이메일 인증이 아직 끝나지 않았어요. 받은편지함의 인증 메일을 확인해 주세요.",
    }

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username and password:
            self.user_cache = authenticate(self.request, username=username, password=password)
            if self.user_cache is None:
                pending = User.objects.filter(email__iexact=username.strip(), is_active=False).first()
                if pending is not None and pending.check_password(password):
                    self.unverified_email = pending.email
                    raise forms.ValidationError(self.error_messages["inactive"], code="inactive")
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class ResetForm(PasswordResetForm):
    """Password reset by email; the mail itself is sent in Korean."""


class DeleteAccountForm(forms.Form):
    password = forms.CharField(label="비밀번호", widget=forms.PasswordInput, strip=False)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("비밀번호가 올바르지 않아요.")
        return password
