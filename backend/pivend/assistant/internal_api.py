"""Internal JSON API the Node agent service calls as its tools.

Every request carries the shared AGENT_INTERNAL_TOKEN and the id of the user
the agent is acting for (X-Pivend-User). Not exposed to browsers.
"""

from __future__ import annotations

import functools
import hmac
import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from pivend.listings.detailpage import SpecError
from pivend.listings.models import ListingDraft
from pivend.listings.renderer import render_detail_page
from pivend.listings.services import DraftError, list_drafts, save_draft
from pivend.listings.titlecheck import check_title
from pivend.naver.errors import NaverAPIError, NaverNotConfigured
from pivend.research import services as research

logger = logging.getLogger(__name__)


def internal_endpoint(methods: tuple[str, ...] = ("POST",)):
    def decorator(view):
        @csrf_exempt
        @functools.wraps(view)
        def wrapper(request: HttpRequest, *args, **kwargs):
            token = settings.AGENT_INTERNAL_TOKEN
            header = request.headers.get("Authorization", "")
            if not token or not hmac.compare_digest(header, f"Bearer {token}"):
                return JsonResponse({"error": "unauthorized"}, status=401)
            if request.method not in methods:
                return JsonResponse({"error": "method not allowed"}, status=405)
            user = get_user_model().objects.filter(pk=request.headers.get("X-Pivend-User") or 0).first()
            if user is None:
                return JsonResponse({"error": "unknown user"}, status=403)
            try:
                body = json.loads(request.body or b"{}") if request.method == "POST" else {}
            except json.JSONDecodeError:
                return JsonResponse({"error": "invalid JSON body"}, status=400)
            if not isinstance(body, dict):
                return JsonResponse({"error": "body must be a JSON object"}, status=400)
            try:
                return JsonResponse(view(request, user, body, *args, **kwargs), safe=False)
            except NaverNotConfigured as exc:
                return JsonResponse({"error": str(exc), "code": "not_configured"}, status=503)
            except NaverAPIError as exc:
                logger.warning("Naver API error: %s %s", exc, exc.body)
                return JsonResponse({"error": f"{exc} {exc.body or ''}".strip(), "code": "upstream"}, status=502)
            except SpecError as exc:
                return JsonResponse({"error": "invalid detail page spec", "details": exc.errors}, status=400)
            except (DraftError, ValueError, TypeError) as exc:
                return JsonResponse({"error": str(exc)}, status=400)

        return wrapper

    return decorator


def _str_list(body: dict, key: str) -> list[str]:
    value = body.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{key} must be a list of strings")
    return value


@internal_endpoint()
def keyword_stats(request, user, body):
    return research.get_keyword_stats(
        _str_list(body, "keywords"), with_competition=bool(body.get("with_competition"))
    )


@internal_endpoint()
def related_keywords(request, user, body):
    return research.get_related_keywords(
        str(body.get("seed") or ""),
        limit=int(body.get("limit") or 50),
        min_searches=int(body.get("min_searches") or 0),
    )


@internal_endpoint()
def keyword_trend(request, user, body):
    return research.get_keyword_trend(
        _str_list(body, "keywords"),
        months=int(body.get("months") or 12),
        time_unit=body.get("time_unit") or "month",
        category=body.get("category") or None,
        device=body.get("device") or None,
        gender=body.get("gender") or None,
        ages=_str_list(body, "ages") or None,
    )


@internal_endpoint()
def competitors(request, user, body):
    query = str(body.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    return research.analyze_competitors(query, sample=int(body.get("sample") or 40))


@internal_endpoint()
def title_check(request, user, body):
    return check_title(
        str(body.get("title") or ""),
        marketplace=body.get("marketplace") or "naver",
        target_keywords=_str_list(body, "target_keywords"),
        brand=body.get("brand") or None,
    )


@internal_endpoint(methods=("GET", "POST"))
def drafts(request, user, body):
    if request.method == "GET":
        return {"drafts": list_drafts(user)}
    return save_draft(user, body).as_dict()


@internal_endpoint(methods=("GET",))
def draft_detail(request, user, body, draft_id: int):
    draft = ListingDraft.objects.filter(owner=user, id=draft_id).first()
    if draft is None:
        raise DraftError(f"Draft {draft_id} not found")
    return draft.as_dict()


@internal_endpoint()
def draft_render(request, user, body, draft_id: int):
    draft = ListingDraft.objects.filter(owner=user, id=draft_id).first()
    if draft is None:
        raise DraftError(f"Draft {draft_id} not found")
    spec = body.get("detail_page")
    if spec is None and not draft.detail_page:
        raise DraftError("Draft has no detail_page spec yet; pass one in detail_page")
    render = render_detail_page(draft, spec)
    return {"draft_id": draft.id, "draft_url": draft.public_url, **render.as_dict()}
