"""Versioned, conservative text normalization."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

WHITESPACE = re.compile(r"\s+")
NORMALIZATION_VERSION = "unicode_nfkc_whitespace_v1"


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:  # NaN
            return ""
    except TypeError:
        pass
    normalized = unicodedata.normalize("NFKC", str(value))
    return WHITESPACE.sub(" ", normalized).strip()
