"""Keep user-supplied URLs from reaching internal services (SSRF)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def is_public_host(host: str) -> bool:
    """True if every address the host resolves to is publicly routable."""
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    return all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in infos)


def check_url(url: str, allow_private: bool = False) -> str | None:
    """Return a Korean error message, or None if the URL is acceptable."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "http:// 또는 https://로 시작하는 주소를 입력해 주세요."
    if parsed.username or parsed.password:
        return "주소에 사용자 이름이나 비밀번호를 넣을 수 없어요. API 키 칸을 사용해 주세요."
    if not allow_private and not is_public_host(parsed.hostname):
        return "인터넷에서 접근할 수 있는 공개 주소만 사용할 수 있어요 (내부·사설 IP 주소는 막혀 있어요)."
    return None
