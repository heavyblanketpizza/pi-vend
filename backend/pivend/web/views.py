from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from pivend.listings.detailpage import SpecError
from pivend.listings.models import ListingDraft
from pivend.listings.renderer import render_detail_page
from pivend.listings.titlecheck import check_title
from pivend.naver.errors import NaverError
from pivend.research import services as research


def home(request):
    return redirect("chat" if request.user.is_authenticated else "login")


def _attempt(fn, *args, **kwargs):
    """Run a research call; return (result, error message)."""
    try:
        return fn(*args, **kwargs), None
    except (NaverError, ValueError) as exc:
        return None, str(exc)


@login_required
def keyword_research(request):
    query = request.GET.get("q", "").strip()
    context = {"query": query}
    if query:
        context["stats"], context["stats_error"] = _attempt(
            research.get_keyword_stats, [query], with_competition=True
        )
        context["related"], context["related_error"] = _attempt(
            research.get_related_keywords, query, limit=50
        )
        context["competitors"], context["competitors_error"] = _attempt(
            research.analyze_competitors, query, sample=40
        )
    return render(request, "web/research.html", context)


@login_required
def drafts(request):
    return render(
        request,
        "web/drafts.html",
        {"drafts": ListingDraft.objects.filter(owner=request.user)},
    )


@login_required
def draft_detail(request, draft_id: int):
    draft = get_object_or_404(ListingDraft, owner=request.user, id=draft_id)
    check = check_title(draft.title, draft.marketplace, draft.target_keywords) if draft.title else None
    return render(
        request,
        "web/draft_detail.html",
        {"draft": draft, "check": check, "render": draft.renders.first()},
    )


@login_required
@require_POST
def draft_render(request, draft_id: int):
    draft = get_object_or_404(ListingDraft, owner=request.user, id=draft_id)
    if not draft.detail_page:
        messages.error(request, "This draft has no 상세페이지 spec yet. Ask the agent to write one.")
    else:
        try:
            render_detail_page(draft)
            messages.success(request, "상세페이지를 다시 렌더링했습니다.")
        except SpecError as exc:
            messages.error(request, f"Invalid spec: {exc}")
    return redirect("draft_detail", draft_id=draft.id)


@login_required
@require_POST
def draft_approve(request, draft_id: int):
    draft = get_object_or_404(ListingDraft, owner=request.user, id=draft_id)
    draft.status = ListingDraft.Status.APPROVED
    draft.save(update_fields=["status", "updated_at"])
    messages.success(request, "Draft approved.")
    return redirect("draft_detail", draft_id=draft.id)
