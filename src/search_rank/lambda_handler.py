"""Observable Lambda bootstrap boundary for the ranking application."""

from __future__ import annotations

import json
import time


def _emit(message: str, **context: object) -> None:
    print(json.dumps({"message": message, **context}, sort_keys=True), flush=True)


_started = time.perf_counter()
_emit("lambda_bootstrap_import_started")

from search_rank.serving.app import handler as handler  # noqa: E402

_emit(
    "lambda_bootstrap_import_succeeded",
    import_duration_ms=(time.perf_counter() - _started) * 1000.0,
)

__all__ = ["handler"]
