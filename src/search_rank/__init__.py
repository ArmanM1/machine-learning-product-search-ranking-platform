"""Machine Learning Product Search Ranking Platform.

The package deliberately exposes only a version marker at its root.  Stable
artifact contracts live in :mod:`search_rank.schemas`, and ranking evaluation
primitives live in :mod:`search_rank.evaluation`.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
