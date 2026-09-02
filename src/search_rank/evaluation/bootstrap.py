"""Deterministic paired, query-level nonparametric bootstrap intervals."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from statistics import fmean, stdev

from search_rank.schemas.evaluation import PairedDifference


class BootstrapAlignmentError(ValueError):
    """Raised when candidate and baseline query sets differ."""


@dataclass(frozen=True)
class BootstrapResult:
    point_estimate: float
    ci_lower: float
    ci_upper: float
    confidence_level: float
    query_count: int
    excluded_query_count: int
    seed: int
    n_resamples: int
    method: str = "paired_nonparametric_percentile"
    resampling_unit: str = "query"
    standard_error: float = 0.0
    included_query_ids: tuple[str, ...] = ()
    excluded_query_ids: tuple[str, ...] = ()

    def as_paired_difference(
        self,
        *,
        metric_name: str,
        candidate_model_id: str,
        baseline_model_id: str,
    ) -> PairedDifference:
        return PairedDifference(
            metric_name=metric_name,
            candidate_model_id=candidate_model_id,
            baseline_model_id=baseline_model_id,
            point_estimate=self.point_estimate,
            ci_lower=self.ci_lower,
            ci_upper=self.ci_upper,
            confidence_level=self.confidence_level,
            query_count=self.query_count,
            excluded_query_count=self.excluded_query_count,
            bootstrap_seed=self.seed,
            bootstrap_resamples=self.n_resamples,
            resampling_unit="query",
        )


def _quantile(sorted_values: list[float], probability: float) -> float:
    """Linear/type-7 sample quantile, implemented to avoid a NumPy dependency."""

    if not sorted_values:
        raise ValueError("cannot take a quantile of an empty sample")
    position = (len(sorted_values) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return sorted_values[lower_index]
    fraction = position - lower_index
    return sorted_values[lower_index] * (1.0 - fraction) + sorted_values[upper_index] * fraction


def _validate_inputs(
    candidate: Mapping[str, float | None],
    baseline: Mapping[str, float | None],
    *,
    n_resamples: int,
    confidence_level: float,
    seed: int,
) -> tuple[list[str], list[str], list[float]]:
    if set(candidate) != set(baseline):
        raise BootstrapAlignmentError(
            "paired bootstrap requires identical query IDs; "
            f"candidate_only={sorted(set(candidate) - set(baseline))}, "
            f"baseline_only={sorted(set(baseline) - set(candidate))}"
        )
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, int) or n_resamples < 1:
        raise ValueError("n_resamples must be a positive integer")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be an integer between 0 and 2**32 - 1")

    included: list[str] = []
    excluded: list[str] = []
    differences: list[float] = []
    # Sorting makes results independent of dict insertion and upstream row order.
    for query_id in sorted(candidate, key=str):
        candidate_value = candidate[query_id]
        baseline_value = baseline[query_id]
        if candidate_value is None or baseline_value is None:
            excluded.append(str(query_id))
            continue
        if isinstance(candidate_value, bool) or isinstance(baseline_value, bool):
            raise TypeError(f"boolean metric value for query {query_id!r}")
        candidate_number = float(candidate_value)
        baseline_number = float(baseline_value)
        if not math.isfinite(candidate_number) or not math.isfinite(baseline_number):
            raise ValueError(f"non-finite metric value for query {query_id!r}")
        included.append(str(query_id))
        differences.append(candidate_number - baseline_number)
    if not differences:
        raise ValueError("paired bootstrap has no non-degenerate aligned query values")
    return included, excluded, differences


def paired_bootstrap(
    candidate: Mapping[str, float | None],
    baseline: Mapping[str, float | None],
    *,
    n_resamples: int = 2_000,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> BootstrapResult:
    """Bootstrap the macro candidate-minus-baseline difference by query.

    Each draw samples ``n_queries`` query differences with replacement.  Pairing
    is preserved because candidate and baseline are subtracted before sampling.
    ``None`` pairs (for example zero-ideal nDCG queries) are excluded and named
    in the result.  The point estimate is computed from the original sample.
    """

    included, excluded, differences = _validate_inputs(
        candidate,
        baseline,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
        seed=seed,
    )
    rng = random.Random(seed)
    query_count = len(differences)
    bootstrap_means: list[float] = []
    for _ in range(n_resamples):
        bootstrap_means.append(
            math.fsum(differences[rng.randrange(query_count)] for _ in range(query_count))
            / query_count
        )
    bootstrap_means.sort()
    alpha = 1.0 - confidence_level
    return BootstrapResult(
        point_estimate=fmean(differences),
        ci_lower=_quantile(bootstrap_means, alpha / 2.0),
        ci_upper=_quantile(bootstrap_means, 1.0 - alpha / 2.0),
        confidence_level=confidence_level,
        query_count=query_count,
        excluded_query_count=len(excluded),
        seed=seed,
        n_resamples=n_resamples,
        standard_error=stdev(bootstrap_means) if len(bootstrap_means) > 1 else 0.0,
        included_query_ids=tuple(included),
        excluded_query_ids=tuple(excluded),
    )


def paired_bootstrap_metrics(
    candidate: Mapping[str, Mapping[str, float | None]],
    baseline: Mapping[str, Mapping[str, float | None]],
    *,
    n_resamples: int = 2_000,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> dict[str, BootstrapResult]:
    """Evaluate multiple named metric maps with stable per-metric seeds."""

    if set(candidate) != set(baseline):
        raise BootstrapAlignmentError("candidate and baseline metric names differ")
    results: dict[str, BootstrapResult] = {}
    for offset, metric_name in enumerate(sorted(candidate)):
        results[metric_name] = paired_bootstrap(
            candidate[metric_name],
            baseline[metric_name],
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            seed=(seed + offset) % (2**32),
        )
    return results


paired_bootstrap_ci = paired_bootstrap
paired_bootstrap_difference = paired_bootstrap

__all__ = [
    "BootstrapAlignmentError",
    "BootstrapResult",
    "paired_bootstrap",
    "paired_bootstrap_ci",
    "paired_bootstrap_difference",
    "paired_bootstrap_metrics",
]
