"""Render a 상세페이지 spec to 860px-wide JPG slices with headless Chromium."""

from __future__ import annotations

import io
import logging
import secrets
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.utils import timezone
from PIL import Image

from pivend.accounts.netguard import is_public_host

from .detailpage import validate_spec
from .models import DetailPageRender, ListingDraft

logger = logging.getLogger(__name__)

# Bundled assets are served to the headless page from this fake origin, so
# renders never depend on a CDN (and look identical in Docker and offline).
FONT_HOST = "https://assets.pivend.internal"
FONT_FILE = "web/fonts/PretendardVariable.woff2"
FONT_PATH = "/fonts/PretendardVariable.woff2"


def _guard_request(route) -> None:
    url = route.request.url
    parsed = urlparse(url)
    if parsed.scheme == "data":
        route.continue_()
    elif parsed.scheme in {"http", "https"} and is_public_host(parsed.hostname or ""):
        route.continue_()
    else:
        logger.warning("Blocked detail-page subresource %s", url)
        route.abort()


def _serve_asset(route) -> None:
    path = urlparse(route.request.url).path
    local = finders.find(FONT_FILE) if path == FONT_PATH else None
    if not local:
        route.abort()
        return
    route.fulfill(
        path=local,
        headers={"Content-Type": "font/woff2", "Access-Control-Allow-Origin": "*"},
    )


def render_html(spec: dict) -> str:
    return render_to_string(
        "listings/detail_page.html",
        {
            "spec": spec,
            "theme": spec["theme"],
            "width": settings.DETAIL_PAGE_WIDTH,
            "font_url": f"{FONT_HOST}{FONT_PATH}",
        },
    )


def screenshot_html(html: str) -> bytes:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    launch_kwargs = {}
    if settings.PLAYWRIGHT_CHROMIUM_EXECUTABLE:
        launch_kwargs["executable_path"] = settings.PLAYWRIGHT_CHROMIUM_EXECUTABLE

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        try:
            page = browser.new_page(
                viewport={"width": settings.DETAIL_PAGE_WIDTH, "height": 1200},
                device_scale_factor=1,
            )
            page.route("**/*", _guard_request)
            # Registered last so it runs first for its URLs.
            page.route(f"{FONT_HOST}/**", _serve_asset)
            page.set_content(html, wait_until="load", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeout:
                logger.warning("Detail page still loading resources after 10s; capturing anyway")
            page.evaluate("document.fonts.ready.then(() => true)")
            return page.screenshot(full_page=True, type="png")
        finally:
            browser.close()


def slice_image(png: bytes, max_height: int) -> tuple[list[bytes], int]:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    width, height = image.size
    slices = []
    for top in range(0, height, max_height):
        part = image.crop((0, top, width, min(top + max_height, height)))
        buffer = io.BytesIO()
        part.save(buffer, format="JPEG", quality=90, optimize=True)
        slices.append(buffer.getvalue())
    return slices, height


def render_detail_page(draft: ListingDraft, spec: dict | None = None) -> DetailPageRender:
    """Validate, render and store a draft's 상세페이지. Saves the spec on the draft."""
    spec = validate_spec(spec if spec is not None else draft.detail_page)
    if draft.detail_page != spec:
        draft.detail_page = spec
        draft.save(update_fields=["detail_page", "updated_at"])

    html = render_html(spec)
    slices, height = slice_image(screenshot_html(html), settings.DETAIL_PAGE_SLICE_HEIGHT)

    # Images are served without a login (the agent and marketplaces fetch them),
    # so the path carries a random part that can't be guessed from the draft id.
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    relative_dir = Path("detail-pages") / str(draft.id) / f"{stamp}-{secrets.token_urlsafe(12)}"
    target_dir = Path(settings.MEDIA_ROOT) / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for n, data in enumerate(slices, start=1):
        name = f"{n:02d}.jpg"
        (target_dir / name).write_bytes(data)
        paths.append((relative_dir / name).as_posix())

    return DetailPageRender.objects.create(
        draft=draft, spec=spec, html=html, images=paths, height=height
    )
