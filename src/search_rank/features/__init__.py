"""Versioned model-input construction."""

from .product_text import (
    ENRICHED_TEMPLATE_VERSION,
    TITLE_TEMPLATE_VERSION,
    render_product_text,
)

__all__ = ["ENRICHED_TEMPLATE_VERSION", "TITLE_TEMPLATE_VERSION", "render_product_text"]
