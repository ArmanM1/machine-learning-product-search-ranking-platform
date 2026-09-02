"""Stable query/product input templates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from search_rank.data.normalize import normalize_text

TITLE_TEMPLATE_VERSION = "title_v1"
ENRICHED_TEMPLATE_VERSION = "enriched_v1"

FIELD_LABELS = (
    ("product_title", "Title"),
    ("product_brand", "Brand"),
    ("product_bullet_point", "Bullet points"),
    ("product_description", "Description"),
)


def render_product_text(row: Mapping[str, Any], template: str = ENRICHED_TEMPLATE_VERSION) -> str:
    title = normalize_text(row.get("product_title"))
    if template == TITLE_TEMPLATE_VERSION:
        return title
    if template != ENRICHED_TEMPLATE_VERSION:
        raise ValueError(f"unknown product template: {template}")
    rendered = []
    for field, label in FIELD_LABELS:
        value = normalize_text(row.get(field))
        if value:
            rendered.append(f"{label}: {value}")
    return "\n".join(rendered)
