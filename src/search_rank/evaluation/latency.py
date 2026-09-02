"""Small, deterministic latency-summary helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import fmean
from typing import Literal

from search_rank.schemas.evaluation import LatencyResult


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def summarize_latency(
    samples_ms: Sequence[float],
    *,
    phase: Literal[
        "cold_model_load",
        "first_request",
        "warm_end_to_end",
        "model_inference",
        "serialization",
    ],
    candidate_count: int | None,
    concurrency: int | None,
    lambda_memory_mb: int | None,
    architecture: str,
    region: str,
    reserved_concurrency: int | None,
    model_revision: str,
) -> LatencyResult:
    if not samples_ms:
        raise ValueError("at least one latency sample is required")
    checked = sorted(float(value) for value in samples_ms)
    if any(not math.isfinite(value) or value < 0 for value in checked):
        raise ValueError("latency samples must be finite and non-negative")
    return LatencyResult(
        phase=phase,
        candidate_count=candidate_count,
        concurrency=concurrency,
        sample_count=len(checked),
        p50_ms=_quantile(checked, 0.50),
        p95_ms=_quantile(checked, 0.95),
        p99_ms=_quantile(checked, 0.99),
        mean_ms=fmean(checked),
        lambda_memory_mb=lambda_memory_mb,
        architecture=architecture,
        region=region,
        reserved_concurrency=reserved_concurrency,
        model_revision=model_revision,
    )


__all__ = ["summarize_latency"]
