from django.contrib import admin

from .models import DetailPageRender, ListingDraft


class DetailPageRenderInline(admin.TabularInline):
    model = DetailPageRender
    extra = 0
    fields = ("created_at", "height", "images")
    readonly_fields = fields


@admin.register(ListingDraft)
class ListingDraftAdmin(admin.ModelAdmin):
    list_display = ("product_name", "title", "marketplace", "owner", "status", "updated_at")
    list_filter = ("marketplace", "status")
    search_fields = ("product_name", "title")
    inlines = [DetailPageRenderInline]
