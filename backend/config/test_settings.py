"""Settings for pytest: fixed secrets, no Naver credentials, throwaway media dir."""

import os
import tempfile

os.environ.update(
    {
        "DJANGO_SECRET_KEY": "test-secret",
        "AGENT_INTERNAL_TOKEN": "test-token",
        "AGENT_URL": "http://agent.test",
        "PUBLIC_BASE_URL": "http://testserver",
        "DJANGO_MEDIA_ROOT": tempfile.mkdtemp(prefix="pivend-media-"),
        "NAVER_SEARCHAD_API_KEY": "",
        "NAVER_SEARCHAD_SECRET_KEY": "",
        "NAVER_SEARCHAD_CUSTOMER_ID": "",
        "NAVER_CLIENT_ID": "",
        "NAVER_CLIENT_SECRET": "",
    }
)
os.environ.pop("DATABASE_URL", None)

from .settings import *  # noqa: E402,F403

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# WhiteNoise warns when STATIC_ROOT hasn't been collected; tests don't serve static files.
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith("whitenoise.")]  # noqa: F405
