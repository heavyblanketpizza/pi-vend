from django.contrib import admin

from .models import ApiCache, KeywordStat


@admin.register(KeywordStat)
class KeywordStatAdmin(admin.ModelAdmin):
    list_display = ("keyword", "pc_searches", "mobile_searches", "competition", "fetched_at")
    search_fields = ("keyword", "normalized")


@admin.register(ApiCache)
class ApiCacheAdmin(admin.ModelAdmin):
    list_display = ("kind", "key", "fetched_at")
    list_filter = ("kind",)
    search_fields = ("key",)
