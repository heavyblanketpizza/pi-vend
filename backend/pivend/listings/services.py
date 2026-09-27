"""Listing draft operations shared by the web UI and the agent API."""

from __future__ import annotations

from .detailpage import validate_spec
from .models import ListingDraft, Marketplace

TEXT_FIELDS = {"product_name": 200, "title": 200, "category_path": 300, "notes": 5000}
LIST_FIELDS = {"tags": 20, "target_keywords": 30}


class DraftError(ValueError):
    pass


def _clean_list(value, name: str, limit: int) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise DraftError(f"{name} must be a list of strings")
    cleaned = [v.strip() for v in value if v.strip()]
    if len(cleaned) > limit:
        raise DraftError(f"{name} accepts at most {limit} entries")
    return cleaned


def save_draft(owner, data: dict) -> ListingDraft:
    """Create a draft, or update the given fields of an existing one (by id)."""
    draft_id = data.get("id")
    if draft_id:
        draft = ListingDraft.objects.filter(owner=owner, id=draft_id).first()
        if draft is None:
            raise DraftError(f"Draft {draft_id} not found")
    else:
        if not str(data.get("product_name") or "").strip():
            raise DraftError("product_name is required for a new draft")
        draft = ListingDraft(owner=owner)

    for name, limit in TEXT_FIELDS.items():
        if name in data and data[name] is not None:
            value = str(data[name]).strip()
            if len(value) > limit:
                raise DraftError(f"{name} is longer than {limit} characters")
            setattr(draft, name, value)
    for name, limit in LIST_FIELDS.items():
        if name in data and data[name] is not None:
            setattr(draft, name, _clean_list(data[name], name, limit))
    if data.get("marketplace") is not None:
        if data["marketplace"] not in Marketplace.values:
            raise DraftError(f"marketplace must be one of {', '.join(Marketplace.values)}")
        draft.marketplace = data["marketplace"]
    if data.get("attributes") is not None:
        if not isinstance(data["attributes"], dict):
            raise DraftError("attributes must be an object")
        draft.attributes = {str(k): v for k, v in data["attributes"].items()}
    if data.get("detail_page") is not None:
        draft.detail_page = validate_spec(data["detail_page"])

    draft.save()
    return draft


def list_drafts(owner, limit: int = 20) -> list[dict]:
    return [
        {
            "id": d.id,
            "marketplace": d.marketplace,
            "product_name": d.product_name,
            "title": d.title,
            "status": d.status,
            "updated_at": d.updated_at.isoformat(),
        }
        for d in ListingDraft.objects.filter(owner=owner)[:limit]
    ]
