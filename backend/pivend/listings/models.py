from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


class Marketplace(models.TextChoices):
    NAVER = "naver", "네이버 스마트스토어"
    COUPANG = "coupang", "쿠팡"


class ListingDraft(models.Model):
    """A listing the agent and the seller work on before anything is published."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listing_drafts")
    marketplace = models.CharField(max_length=20, choices=Marketplace.choices, default=Marketplace.NAVER)
    product_name = models.CharField(max_length=200, help_text="Internal name for the product")
    title = models.CharField(max_length=200, blank=True, help_text="상품명 shown on the marketplace")
    tags = models.JSONField(default=list, blank=True)
    target_keywords = models.JSONField(default=list, blank=True)
    category_path = models.CharField(max_length=300, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    detail_page = models.JSONField(default=dict, blank=True, help_text="상세페이지 section spec")
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or self.product_name

    @property
    def public_url(self) -> str:
        return f"{settings.PUBLIC_BASE_URL}/drafts/{self.id}/"

    def as_dict(self) -> dict:
        latest = self.renders.order_by("-created_at").first()
        return {
            "id": self.id,
            "url": self.public_url,
            "marketplace": self.marketplace,
            "product_name": self.product_name,
            "title": self.title,
            "tags": self.tags,
            "target_keywords": self.target_keywords,
            "category_path": self.category_path,
            "attributes": self.attributes,
            "detail_page": self.detail_page,
            "notes": self.notes,
            "status": self.status,
            "latest_render": latest.as_dict() if latest else None,
            "updated_at": self.updated_at.isoformat(),
        }


class DetailPageRender(models.Model):
    """One rendering of a draft's 상세페이지 into 860px-wide JPG slices."""

    draft = models.ForeignKey(ListingDraft, on_delete=models.CASCADE, related_name="renders")
    spec = models.JSONField()
    html = models.TextField()
    images = models.JSONField(default=list, help_text="Paths relative to MEDIA_ROOT")
    height = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def image_urls(self) -> list[str]:
        return [f"{settings.MEDIA_URL}{path}" for path in self.images]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "images": [f"{settings.PUBLIC_BASE_URL}{url}" for url in self.image_urls()],
            "height": self.height,
            "created_at": self.created_at.isoformat(),
        }


@receiver(post_delete, sender=DetailPageRender)
def delete_render_files(sender, instance: DetailPageRender, **kwargs):
    """Remove the JPG slices when a render (or its draft or owner) is deleted."""
    root = Path(settings.MEDIA_ROOT)
    folders = set()
    for path in instance.images:
        file = root / path
        file.unlink(missing_ok=True)
        folders.add(file.parent)
    for folder in folders:
        try:
            folder.rmdir()
            folder.parent.rmdir()  # the draft's folder, once its last render is gone
        except OSError:
            pass
