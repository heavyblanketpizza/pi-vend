"""The seller's own store data: sales, traffic, inflow keywords and ads, per day.

Data arrives from report uploads (스마트스토어 비즈어드바이저, 쿠팡 WING / 광고 exports)
today, and from the marketplace APIs once the store connections are registered.
"""

from django.conf import settings
from django.db import models

from pivend.listings.models import Marketplace


class Store(models.Model):
    class Source(models.TextChoices):
        UPLOAD = "upload", "파일 업로드"
        API = "api", "API 연동"
        DEMO = "demo", "데모 데이터"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stores")
    marketplace = models.CharField(max_length=20, choices=Marketplace.choices)
    name = models.CharField(max_length=100)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.UPLOAD)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["marketplace", "name"]
        constraints = [models.UniqueConstraint(fields=["owner", "marketplace", "name"], name="unique_store_name")]

    def __str__(self):
        return f"{self.name} ({self.get_marketplace_display()})"


class Product(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["store", "name"], name="unique_product_name")]

    def __str__(self):
        return self.name


class DailySales(models.Model):
    """Store-level rows have product=None; product-level rows carry the product."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="sales")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True, related_name="sales")
    date = models.DateField()
    orders = models.PositiveIntegerField(default=0)
    units = models.PositiveIntegerField(default=0)
    revenue = models.BigIntegerField(default=0, help_text="KRW")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["store", "product", "date"], name="unique_daily_sales")]
        indexes = [models.Index(fields=["store", "date"])]


class DailyTraffic(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="traffic")
    date = models.DateField()
    visits = models.PositiveIntegerField(default=0)
    page_views = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["store", "date"], name="unique_daily_traffic")]


class KeywordInflow(models.Model):
    """Search keywords that brought shoppers to the store (유입 키워드)."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="keyword_inflows")
    date = models.DateField()
    keyword = models.CharField(max_length=100)
    visits = models.PositiveIntegerField(default=0)
    orders = models.PositiveIntegerField(default=0)
    revenue = models.BigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["store", "date", "keyword"], name="unique_keyword_inflow")]


class AdDaily(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="ads")
    date = models.DateField()
    keyword = models.CharField(max_length=100, blank=True)
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    spend = models.BigIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    revenue = models.BigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["store", "date", "keyword"], name="unique_ad_daily")]


class DataImport(models.Model):
    class Kind(models.TextChoices):
        SALES = "sales", "판매 실적"
        TRAFFIC = "traffic", "방문 통계"
        KEYWORDS = "keywords", "유입 키워드"
        ADS = "ads", "광고 성과"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="imports")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    filename = models.CharField(max_length=255)
    rows = models.PositiveIntegerField(default=0)
    first_date = models.DateField(null=True, blank=True)
    last_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
