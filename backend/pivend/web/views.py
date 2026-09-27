import io
import zipfile
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from pivend.accounts import ratelimit
from pivend.listings.detailpage import SpecError
from pivend.listings.models import ListingDraft
from pivend.listings.renderer import render_detail_page
from pivend.listings.titlecheck import HARD_LIMIT, RECOMMENDED_MAX, check_title
from pivend.naver.errors import NaverError, NaverNotConfigured
from pivend.research import services as research

from .charts import area_chart, price_positions

RECENT_SEARCHES = 8


def _attempt(fn, *args, **kwargs):
    """Run a research call; return (result, error message)."""
    try:
        return fn(*args, **kwargs), None
    except NaverNotConfigured:
        return None, None  # the page shows a single setup card instead
    except (NaverError, ValueError) as exc:
        return None, str(exc)


def _remember(request, query: str) -> list[str]:
    recent = [q for q in request.session.get("recent_searches", []) if q != query]
    recent = [query, *recent][:RECENT_SEARCHES]
    request.session["recent_searches"] = recent
    return recent


@login_required
def keyword_research(request):
    query = " ".join(request.GET.get("q", "").split())[:50]
    account = research.account_for(request.user)
    sources = {"searchad": account.has_searchad, "openapi": account.has_openapi}
    context = {
        "query": query,
        "sources": sources,
        "recent": request.session.get("recent_searches", []),
    }
    if query and (sources["searchad"] or sources["openapi"]) and not ratelimit.hit("research", request.user.pk):
        context["rate_limited"] = True
    elif query:
        context["recent"] = [q for q in _remember(request, query) if q != query]
        stats, context["stats_error"] = _attempt(
            research.get_keyword_stats, account, [query], with_competition=sources["openapi"]
        )
        main = stats["keywords"][0] if stats and stats["keywords"] else None
        context["main"] = main if main and main.get("found") else None
        if context["main"]:
            volume = context["main"]["monthly_searches"]
            volume["mobile_pct"] = round(volume["mobile"] / volume["total"] * 100) if volume["total"] else 0
            volume["pc_pct"] = 100 - volume["mobile_pct"]
        context["main_missing"] = bool(stats) and not context["main"]

        related, context["related_error"] = _attempt(research.get_related_keywords, account, query, limit=40)
        if related:
            top = max((k["total"] for k in related["keywords"]), default=0)
            for k in related["keywords"]:
                k["bar"] = round(k["total"] / top * 100, 1) if top else 0
                k["mobile_share"] = round(k["mobile"] / k["total"] * 100) if k["total"] else 0
        context["related"] = related

        competitors, context["competitors_error"] = _attempt(research.analyze_competitors, account, query, sample=40)
        if competitors:
            sampled = competitors["sampled"] or 1
            top_share = max((t["share"] for t in competitors["top_tokens"]), default=1) or 1
            for t in competitors["top_tokens"]:
                t["weight"] = round(t["share"] / top_share, 2)
            for c in competitors["categories"]:
                c["pct"] = round(c["count"] / sampled * 100)
            competitors["price_pos"] = price_positions(competitors["price"])
        context["competitors"] = competitors

        trend, context["trend_error"] = _attempt(research.get_keyword_trend, account, [query], months=12)
        series = trend["series"][0] if trend and trend["series"] else None
        context["trend"] = series
        context["chart"] = area_chart(series["points"], trend["time_unit"]) if series else None

        context["agent_url"] = reverse("chat") + "?" + urlencode(
            {"prompt": f"'{query}' 키워드로 상품을 등록하려고 해요. 타깃 키워드를 골라서 스마트스토어 상품명과 태그를 추천해 주세요."}
        )
    return render(request, "web/research.html", context)


@login_required
def drafts(request):
    base = ListingDraft.objects.filter(owner=request.user)
    counts = base.aggregate(
        all=Count("id"),
        draft=Count("id", filter=Q(status=ListingDraft.Status.DRAFT)),
        approved=Count("id", filter=Q(status=ListingDraft.Status.APPROVED)),
    )
    status = request.GET.get("status", "")
    items = base.filter(status=status) if status in ListingDraft.Status.values else base
    items = list(items.prefetch_related("renders"))
    for draft in items:
        latest = next(iter(draft.renders.all()), None)
        draft.cover = latest.image_urls()[0] if latest and latest.images else None
    return render(request, "web/drafts.html", {"drafts": items, "counts": counts, "status": status})


@login_required
def draft_detail(request, draft_id: int):
    draft = get_object_or_404(ListingDraft, owner=request.user, id=draft_id)
    check = check_title(draft.title, draft.marketplace, draft.target_keywords) if draft.title else None
    meter = None
    if check:
        length = check["length"]
        meter = {
            "pct": min(100, round(length / HARD_LIMIT * 100)),
            "level": "error" if length > HARD_LIMIT else "warning" if length > RECOMMENDED_MAX else "ok",
            "recommended": RECOMMENDED_MAX,
            "limit": HARD_LIMIT,
        }
    return render(
        request,
        "web/draft_detail.html",
        {
            "draft": draft,
            "check": check,
            "meter": meter,
            "render": draft.renders.first(),
            "category_parts": [p.strip() for p in draft.category_path.split(">") if p.strip()],
        },
    )


@login_required
@require_POST
def draft_render(request, draft_id: int):
    draft = get_object_or_404(ListingDraft, owner=request.user, id=draft_id)
    if not draft.detail_page:
        messages.error(request, "상세페이지 구성이 아직 없어요. 에이전트에게 만들어 달라고 해보세요.")
    else:
        try:
            render_detail_page(draft)
            messages.success(request, "상세페이지를 다시 렌더링했어요.")
        except SpecError as exc:
            messages.error(request, f"상세페이지 구성 오류: {exc}")
    return redirect("draft_detail", draft_id=draft.id)


@login_required
@require_POST
def draft_approve(request, draft_id: int):
    draft = get_object_or_404(ListingDraft, owner=request.user, id=draft_id)
    draft.status = ListingDraft.Status.APPROVED
    draft.save(update_fields=["status", "updated_at"])
    messages.success(request, "초안을 승인했어요.")
    return redirect("draft_detail", draft_id=draft.id)


@login_required
def draft_download(request, draft_id: int):
    """All slices of the latest render as a zip, ready for the 스마트에디터 upload."""
    draft = get_object_or_404(ListingDraft, owner=request.user, id=draft_id)
    render_obj = draft.renders.first()
    if render_obj is None or not render_obj.images:
        raise Http404("No rendered detail page")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for path in render_obj.images:
            file = Path(settings.MEDIA_ROOT) / path
            if file.exists():
                archive.write(file, arcname=f"detail-{Path(path).name}")
    buffer.seek(0)
    name = f"{draft.product_name or 'draft'}-상세페이지.zip".replace("/", "-")
    return FileResponse(buffer, as_attachment=True, filename=name, content_type="application/zip")


# ------------------------------------------------------------------ dashboard
def _delta_class(delta, up_is_good=True):
    if delta is None or delta == 0:
        return "flat"
    return "up" if (delta > 0) == up_is_good else "down"


@login_required
def dashboard(request):
    from pivend.accounts.views import setup_steps
    from pivend.store import analytics
    from pivend.store.insights import build_insights
    from pivend.store.models import Store

    from .charts import column_chart, line_chart, sparkline

    try:
        days = int(request.GET.get("days", 30))
    except ValueError:
        days = 30
    store_id = request.GET.get("store") or None
    store_id = int(store_id) if store_id and store_id.isdigit() else None
    data = analytics.dashboard(request.user, days, store_id)
    context = {"stores": Store.objects.filter(owner=request.user), "store_id": store_id, "days": days, "periods": analytics.PERIODS}
    steps = setup_steps(request.user)
    done = sum(s["done"] for s in steps)
    if done < len(steps):
        context.update(steps=steps, steps_done=done)
    if data is None:
        return render(request, "web/dashboard.html", context)

    kpis = data["kpis"]
    for k in kpis:
        k["spark"] = sparkline(k["series"]) if k["series"] else None
        k["trend"] = _delta_class(k["delta"])
    for p in data["products"]:
        p["spark"] = sparkline(p["series"], width=96, height=24)
        p["trend"] = _delta_class(p["delta"])
    daily = data["daily"]
    chart = line_chart(
        daily["days"],
        [
            {"name": "이번 기간", "values": daily["revenue"], "role": "primary"},
            {"name": "직전 기간", "values": daily["revenue_prev"], "role": "compare"},
        ],
        height=330,
    )
    peak_weekday = max(data["weekday"], key=lambda w: w["value"])
    weekday = column_chart(
        [{"label": w["label"], "value": w["value"], "highlight": w is peak_weekday} for w in data["weekday"]]
    )
    ads = data["ads"]
    if ads:
        peak_spend = max((k["spend"] for k in ads["keywords"]), default=1) or 1
        for k in ads["keywords"]:
            k["bar"] = round(k["spend"] / peak_spend * 100, 1)
    context.update(
        data=data,
        hero=kpis[0],
        tiles=kpis[1:],
        chart=chart,
        chart_rows=list(zip(daily["days"], daily["revenue"], daily["revenue_prev"], daily["orders"])),
        weekday=weekday,
        insights=build_insights(data),
    )
    return render(request, "web/dashboard.html", context)


@login_required
@require_POST
def demo_data(request):
    from pivend.store.demo import create_demo

    create_demo(request.user)
    messages.success(request, "데모 스토어 데이터를 만들었어요. 실제 리포트를 올리면 함께 표시돼요.")
    return redirect("dashboard")


@login_required
def data_sources(request):
    from pivend.store.importers import ImportError_, import_report
    from pivend.store.models import DataImport, Store

    stores = Store.objects.filter(owner=request.user)
    if request.method == "POST":
        upload = request.FILES.get("file")
        store_id = request.POST.get("store")
        new_name = request.POST.get("new_store", "").strip()
        marketplace = request.POST.get("marketplace", "naver")
        if upload is None:
            messages.error(request, "업로드할 파일을 선택해 주세요.")
        elif upload.size > 20 * 1024 * 1024:
            messages.error(request, "파일은 20MB까지 올릴 수 있어요.")
        else:
            if store_id == "new" or not stores.exists():
                if not new_name:
                    messages.error(request, "새 스토어 이름을 입력해 주세요.")
                    return redirect("data_sources")
                store, _ = Store.objects.get_or_create(owner=request.user, marketplace=marketplace, name=new_name[:100])
            else:
                store = get_object_or_404(Store, owner=request.user, id=store_id)
            kind = request.POST.get("kind") or None
            try:
                result = import_report(store, upload.name, upload.read(), kind if kind in DataImport.Kind.values else None)
                messages.success(
                    request,
                    f"{DataImport.Kind(result.kind).label} {result.rows:,}행을 가져왔어요 ({result.first_date} ~ {result.last_date}).",
                )
            except ImportError_ as exc:
                messages.error(request, str(exc))
        return redirect("data_sources")
    imports = DataImport.objects.filter(store__owner=request.user).select_related("store")[:20]
    return render(
        request,
        "web/data.html",
        {"stores": stores, "imports": imports, "kinds": DataImport.Kind.choices, "marketplaces": ListingDraft._meta.get_field("marketplace").choices},
    )


@login_required
@require_POST
def delete_store(request, store_id: int):
    from pivend.store.models import Store

    store = get_object_or_404(Store, owner=request.user, id=store_id)
    store.delete()
    messages.success(request, f"'{store.name}' 스토어와 데이터를 삭제했어요.")
    return redirect("data_sources")
