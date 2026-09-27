"""Encryption for secrets stored in the database (API keys, tokens).

Keys come from CREDENTIAL_ENCRYPTION_KEYS: a comma-separated list of Fernet
keys, newest first. Values are always encrypted with the first key and can be
decrypted with any of them, so keys can be rotated by prepending a new one and
running `manage.py rotate_credentials`.
"""

from __future__ import annotations

import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SecretError(Exception):
    """A stored secret can't be decrypted with any configured key."""


@lru_cache(maxsize=4)
def _fernet(keys: tuple[str, ...]) -> MultiFernet:
    return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])


def fernet() -> MultiFernet:
    if not settings.CREDENTIAL_ENCRYPTION_KEYS:
        raise ImproperlyConfigured("Set CREDENTIAL_ENCRYPTION_KEYS (see .env.example)")
    return _fernet(tuple(settings.CREDENTIAL_ENCRYPTION_KEYS))


def encrypt(data: dict) -> str:
    return fernet().encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()


def decrypt(token: str) -> dict:
    if not token:
        return {}
    try:
        return json.loads(fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise SecretError("저장된 키를 복호화할 수 없어요. 암호화 키 설정을 확인해 주세요.") from exc


def rotate(token: str) -> str:
    return fernet().rotate(token.encode()).decode() if token else token
