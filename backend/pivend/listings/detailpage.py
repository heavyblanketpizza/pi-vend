"""상세페이지 spec: a list of typed sections the agent fills in.

The agent writes the copy as structured sections; the template turns them into
an 860px-wide page. Keeping text out of generated images means Korean
typography always renders correctly.
"""

from __future__ import annotations

import re

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_SECTIONS = 20
MAX_TEXT = 1000

DEFAULT_THEME = {
    "accent": "#FF5A36",
    "background": "#FFFFFF",
    "text": "#1A1A1A",
    "muted": "#6B7280",
    "surface": "#F5F5F4",
}

# field name -> kind. "*" suffix marks required fields.
SECTION_FIELDS: dict[str, dict[str, str]] = {
    "hero": {"eyebrow": "text", "headline*": "text", "subheadline": "text", "image_url": "url", "badges": "texts"},
    "problem": {"headline*": "text", "points*": "texts"},
    "benefits": {"headline*": "text", "items*": "items:title*,body,icon"},
    "feature": {"headline*": "text", "body": "text", "image_url": "url", "caption": "text"},
    "specs": {"headline": "text", "rows*": "items:label*,value*"},
    "howto": {"headline*": "text", "steps*": "texts"},
    "trust": {"headline*": "text", "items*": "items:title*,body"},
    "faq": {"headline": "text", "items*": "items:q*,a*"},
    "notice": {"headline*": "text", "body*": "text"},
    "text": {"headline": "text", "body*": "text"},
}

SECTION_HELP = {
    "hero": "Opening hook: headline, optional eyebrow/subheadline/badges and a product image URL.",
    "problem": "Pain points the product solves (points: list of strings).",
    "benefits": "Key benefits (items: title, body, optional emoji icon).",
    "feature": "One feature explained, optionally with an image and caption.",
    "specs": "Spec table (rows: label/value). Only facts the seller provided.",
    "howto": "Usage steps (steps: list of strings).",
    "trust": "Certifications, guarantees, company facts supplied by the seller.",
    "faq": "Questions and answers (items: q/a).",
    "notice": "Shipping, exchange and return information.",
    "text": "Free text block.",
}


class SpecError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _text(value, path: str, errors: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        errors.append(f"{path} must be a string")
        return None
    text = str(value).strip()
    if len(text) > MAX_TEXT:
        errors.append(f"{path} is longer than {MAX_TEXT} characters")
        return None
    return text or None


def _url(value, path: str, errors: list[str]) -> str | None:
    text = _text(value, path, errors)
    if text and not re.match(r"^https?://", text):
        errors.append(f"{path} must be an http(s) URL")
        return None
    return text


def _field(kind: str, value, path: str, errors: list[str]):
    if kind == "text":
        return _text(value, path, errors)
    if kind == "url":
        return _url(value, path, errors)
    if kind == "texts":
        if value is None:
            return None
        if not isinstance(value, list):
            errors.append(f"{path} must be a list of strings")
            return None
        out = [t for i, v in enumerate(value) if (t := _text(v, f"{path}[{i}]", errors))]
        return out or None
    if kind.startswith("items:"):
        if value is None:
            return None
        if not isinstance(value, list):
            errors.append(f"{path} must be a list of objects")
            return None
        subfields = kind.removeprefix("items:").split(",")
        out = []
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"{path}[{i}] must be an object")
                continue
            clean = {}
            for sub in subfields:
                name = sub.rstrip("*")
                text = _text(item.get(name), f"{path}[{i}].{name}", errors)
                if text:
                    clean[name] = text
                elif sub.endswith("*"):
                    errors.append(f"{path}[{i}].{name} is required")
            if clean:
                out.append(clean)
        return out or None
    raise AssertionError(f"unknown field kind {kind}")


def validate_spec(spec: dict) -> dict:
    """Return a cleaned copy of the spec or raise SpecError listing every problem."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        raise SpecError(["spec must be an object with 'sections'"])

    theme = dict(DEFAULT_THEME)
    for key, value in (spec.get("theme") or {}).items():
        if key not in DEFAULT_THEME:
            errors.append(f"theme.{key} is not a theme color ({', '.join(DEFAULT_THEME)})")
        elif not isinstance(value, str) or not HEX_RE.match(value):
            errors.append(f"theme.{key} must be a #RRGGBB color")
        else:
            theme[key] = value

    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections must be a non-empty list")
        sections = []
    if len(sections) > MAX_SECTIONS:
        errors.append(f"at most {MAX_SECTIONS} sections")

    clean_sections = []
    for i, section in enumerate(sections[:MAX_SECTIONS]):
        path = f"sections[{i}]"
        if not isinstance(section, dict):
            errors.append(f"{path} must be an object")
            continue
        kind = section.get("type")
        if kind not in SECTION_FIELDS:
            errors.append(f"{path}.type must be one of: {', '.join(SECTION_FIELDS)}")
            continue
        clean = {"type": kind}
        for field, field_kind in SECTION_FIELDS[kind].items():
            name = field.rstrip("*")
            value = _field(field_kind, section.get(name), f"{path}.{name}", errors)
            if value is not None:
                clean[name] = value
            elif field.endswith("*"):
                errors.append(f"{path}.{name} is required for '{kind}' sections")
        clean_sections.append(clean)

    if errors:
        raise SpecError(errors)
    return {"theme": theme, "sections": clean_sections}
