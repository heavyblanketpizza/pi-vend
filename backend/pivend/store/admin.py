from django.contrib import admin

from .models import AdDaily, DailySales, DailyTraffic, DataImport, KeywordInflow, Product, Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "marketplace", "owner", "source", "created_at")
    list_filter = ("marketplace", "source")


@admin.register(DataImport)
class DataImportAdmin(admin.ModelAdmin):
    list_display = ("store", "kind", "filename", "rows", "first_date", "last_date", "created_at")


for model in (Product, DailySales, DailyTraffic, KeywordInflow, AdDaily):
    admin.site.register(model)
