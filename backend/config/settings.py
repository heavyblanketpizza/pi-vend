"""Django settings for pi-vend.

Configuration comes from environment variables (see ../.env.example).
A .env file at the repository root is loaded automatically for local dev.
"""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
for candidate in (REPO_ROOT / ".env", BASE_DIR / ".env"):
    if candidate.exists():
        environ.Env.read_env(candidate)
        break

DEBUG = env.bool("DJANGO_DEBUG", default=False)
# An empty value (as in .env.example) counts as unset.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="") or ("dev-insecure-change-me" if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local development)")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pivend.accounts",
    "pivend.naver",
    "pivend.research",
    "pivend.listings",
    "pivend.assistant",
    "pivend.store",
    "pivend.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "pivend.web.context_processors.shell",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = env("DJANGO_STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))
MEDIA_URL = "/media/"
MEDIA_ROOT = env("DJANGO_MEDIA_ROOT", default=str(BASE_DIR / "media"))
# Rendered detail-page images are served by Django itself unless a proxy/CDN
# takes over. Fine for a single-server deployment.
SERVE_MEDIA = env.bool("SERVE_MEDIA", default=True)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTHENTICATION_BACKENDS = ["pivend.accounts.backends.EmailBackend"]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- Accounts -------------------------------------------------------------------
# Anyone can create an account when true; otherwise only admins add users.
SIGNUPS_OPEN = env.bool("SIGNUPS_OPEN", default=True)
# New accounts must confirm their email address before they can log in.
EMAIL_VERIFICATION = env.bool("EMAIL_VERIFICATION", default=True)
# smtp+tls://user:password@smtp.example.com:587 — prints mail to the console by default.
vars().update(env.email_url("EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Pi-Vend <no-reply@localhost>")
# Password reset and verification links are valid this long.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24

# Users' API keys are encrypted with these Fernet keys (newest first). Generate one with
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Without keys (and DEBUG off) nothing can be saved; `manage.py check --deploy` reports it.
CREDENTIAL_ENCRYPTION_KEYS = env.list("CREDENTIAL_ENCRYPTION_KEYS", default=[])
if not CREDENTIAL_ENCRYPTION_KEYS and DEBUG:
    import base64
    import hashlib

    # Local development only: derived from SECRET_KEY so the dev server just works.
    CREDENTIAL_ENCRYPTION_KEYS = [base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()]
# Users may point the agent at their own LLM server. Private/internal addresses are
# refused unless this is on (single-tenant self-hosting, e.g. http://llamacpp:8080/v1).
ALLOW_PRIVATE_LLM_URLS = env.bool("ALLOW_PRIVATE_LLM_URLS", default=DEBUG)

# Per-user request limits (count, seconds).
RATE_LIMITS = {
    "chat": (env.int("RATE_LIMIT_CHAT_PER_HOUR", default=60), 3600),
    "research": (env.int("RATE_LIMIT_RESEARCH_PER_HOUR", default=120), 3600),
    "credential_test": (20, 3600),
    "signup": (10, 3600),
    "email": (5, 3600),
}
# Set when a reverse proxy you control sets X-Forwarded-For (used for sign-up limits).
TRUST_X_FORWARDED_FOR = env.bool("TRUST_X_FORWARDED_FOR", default=False)
CACHES = {"default": env.cache_url("CACHE_URL", default="locmemcache://")}

# --- Naver APIs ---------------------------------------------------------------
# Each user connects their own keys (설정 > API 연결).
# How long cached keyword/shopping lookups stay fresh.
RESEARCH_CACHE_HOURS = env.int("RESEARCH_CACHE_HOURS", default=24)

# --- Agent service --------------------------------------------------------------
AGENT_URL = env("AGENT_URL", default="http://localhost:3001")
# Shared secret between Django and the Node agent service (both directions).
AGENT_INTERNAL_TOKEN = env("AGENT_INTERNAL_TOKEN", default="dev-internal-token" if DEBUG else "")
# Public base URL the agent uses when it links to rendered images.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8000")

# --- Detail page rendering -----------------------------------------------------
# Leave empty to use Playwright's bundled browser.
PLAYWRIGHT_CHROMIUM_EXECUTABLE = env("PLAYWRIGHT_CHROMIUM_EXECUTABLE", default="")
DETAIL_PAGE_WIDTH = 860
DETAIL_PAGE_SLICE_HEIGHT = env.int("DETAIL_PAGE_SLICE_HEIGHT", default=3000)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
