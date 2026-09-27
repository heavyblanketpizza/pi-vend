from django.urls import path

from . import internal_api as api

urlpatterns = [
    path("research/keyword-stats", api.keyword_stats),
    path("research/related-keywords", api.related_keywords),
    path("research/trend", api.keyword_trend),
    path("research/competitors", api.competitors),
    path("listings/check-title", api.title_check),
    path("store/overview", api.store_overview),
    path("listings/drafts", api.drafts),
    path("listings/drafts/<int:draft_id>", api.draft_detail),
    path("listings/drafts/<int:draft_id>/render", api.draft_render),
]
