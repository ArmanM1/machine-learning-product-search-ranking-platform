"""Frozen, deterministic query-slice assignment and paired comparisons."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Literal, cast

from search_rank.schemas.evaluation import SliceResult

from .bootstrap import paired_bootstrap
from .metrics import Relevance, gain_for

# These boundaries are deliberately constants so a release can record/version
# them before held-out access instead of selecting bins after seeing results.
SLICE_DEFINITION_VERSION = "predeclared_slices_v1"
QUERY_TOKEN_LENGTH_BOUNDARIES = (1, 2, 4)  # 1, 2, 3-4, >=5
TEXT_COMPLETENESS_BOUNDARIES = (0.5, 0.75)  # sparse, partial, rich
LEXICAL_OVERLAP_BOUNDARIES = (0.0, 1 / 3, 2 / 3)  # none, low, medium, high
DEFAULT_MIN_SLICE_QUERIES = 30

_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class CandidateSliceFeatures:
    title: str
    relevance: Relevance
    brand: str = ""
    bullet_point: str = ""
    description: str = ""
    product_source: str = ""


@dataclass(frozen=True)
class SliceHighlights:
    strongest_improvement: SliceResult | None
    largest_regression: SliceResult | None
    largest_uncertain_change: SliceResult | None
    inadequate_sample_slices: tuple[SliceResult, ...]


def tokenize_for_slices(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _TOKEN.finditer(text))


def query_token_length_bin(query: str) -> str:
    count = len(tokenize_for_slices(query))
    if count == 0:
        raise ValueError("query must contain at least one token")
    if count == 1:
        return "1_token"
    if count == 2:
        return "2_tokens"
    if count <= 4:
        return "3_to_4_tokens"
    return "5_plus_tokens"


def candidate_label_composition_bin(relevances: Sequence[Relevance]) -> str:
    if not relevances:
        raise ValueError("a query slice requires at least one candidate")
    gains = [gain_for(value) for value in relevances]
    if 3 in gains:
        return "exact_present"
    if 2 in gains:
        return "substitute_without_exact"
    if 1 in gains:
        return "complement_only"
    return "all_irrelevant"


def brand_presence_bin(candidates: Sequence[CandidateSliceFeatures]) -> str:
    if not candidates:
        raise ValueError("a query slice requires at least one candidate")
    present = sum(bool(candidate.brand.strip()) for candidate in candidates)
    if present == 0:
        return "brand_none"
    if present == len(candidates):
        return "brand_all"
    return "brand_partial"


def product_text_completeness_bin(candidates: Sequence[CandidateSliceFeatures]) -> str:
    """Bin the share of title/brand/bullets/description fields present."""

    if not candidates:
        raise ValueError("a query slice requires at least one candidate")
    populated = sum(
        bool(value.strip())
        for candidate in candidates
        for value in (
            candidate.title,
            candidate.brand,
            candidate.bullet_point,
            candidate.description,
        )
    )
    ratio = populated / (4 * len(candidates))
    if ratio < TEXT_COMPLETENESS_BOUNDARIES[0]:
        return "text_sparse_lt_50pct"
    if ratio < TEXT_COMPLETENESS_BOUNDARIES[1]:
        return "text_partial_50_to_lt_75pct"
    return "text_rich_75_to_100pct"


def query_title_lexical_overlap_bin(
    query: str, candidates: Sequence[CandidateSliceFeatures]
) -> str:
    """Use the maximum fraction of unique query tokens covered by a title."""

    if not candidates:
        raise ValueError("a query slice requires at least one candidate")
    query_tokens = set(tokenize_for_slices(query))
    if not query_tokens:
        raise ValueError("query must contain at least one token")
    maximum = max(
        len(query_tokens & set(tokenize_for_slices(candidate.title))) / len(query_tokens)
        for candidate in candidates
    )
    if maximum == LEXICAL_OVERLAP_BOUNDARIES[0]:
        return "overlap_none"
    if maximum <= LEXICAL_OVERLAP_BOUNDARIES[1]:
        return "overlap_low_le_1_3"
    if maximum <= LEXICAL_OVERLAP_BOUNDARIES[2]:
        return "overlap_medium_le_2_3"
    return "overlap_high_gt_2_3"


def product_source_bin(candidates: Sequence[CandidateSliceFeatures]) -> str | None:
    sources = {candidate.product_source.strip() for candidate in candidates}
    sources.discard("")
    if not sources:
        return None
    if len(sources) == 1:
        return f"source:{next(iter(sources))}"
    return "source:mixed"


def assign_predeclared_slices(
    query: str, candidates: Sequence[CandidateSliceFeatures]
) -> dict[str, str]:
    """Assign five mandatory query-level dimensions and optional source."""

    assignments = {
        "query_token_length": query_token_length_bin(query),
        "candidate_label_composition": candidate_label_composition_bin(
            [candidate.relevance for candidate in candidates]
        ),
        "brand_presence": brand_presence_bin(candidates),
        "product_text_completeness": product_text_completeness_bin(candidates),
        "query_title_lexical_overlap": query_title_lexical_overlap_bin(query, candidates),
    }
    source = product_source_bin(candidates)
    if source is not None:
        assignments["product_source"] = source
    return assignments


def _slice_seed(seed: int, dimension: str, slice_name: str) -> int:
    digest = hashlib.sha256(f"{dimension}\0{slice_name}".encode()).digest()
    return (seed + int.from_bytes(digest[:4], "big")) % (2**32)


def evaluate_slices(
    candidate_per_query: Mapping[str, float | None],
    baseline_per_query: Mapping[str, float | None],
    assignments: Mapping[str, Mapping[str, str]],
    *,
    n_resamples: int = 2_000,
    confidence_level: float = 0.95,
    seed: int = 42,
    minimum_query_count: int = DEFAULT_MIN_SLICE_QUERIES,
) -> list[SliceResult]:
    """Build paired intervals for each predeclared query slice."""

    if set(candidate_per_query) != set(baseline_per_query):
        raise ValueError("candidate and baseline query IDs differ")
    if set(candidate_per_query) != set(assignments):
        raise ValueError("slice assignments must exist for every evaluated query")
    if minimum_query_count < 1:
        raise ValueError("minimum_query_count must be positive")

    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for query_id in sorted(assignments):
        for dimension, slice_name in sorted(assignments[query_id].items()):
            groups[(dimension, slice_name)].append(query_id)

    results: list[SliceResult] = []
    for (dimension, slice_name), query_ids in sorted(groups.items()):
        candidate = {query_id: candidate_per_query[query_id] for query_id in query_ids}
        baseline = {query_id: baseline_per_query[query_id] for query_id in query_ids}
        valid = [
            query_id
            for query_id in query_ids
            if candidate[query_id] is not None and baseline[query_id] is not None
        ]
        if not valid:
            results.append(
                SliceResult(
                    dimension=dimension,
                    slice_name=slice_name,
                    query_count=0,
                    excluded_query_count=len(query_ids),
                    candidate_value=None,
                    baseline_value=None,
                    point_estimate=None,
                    ci_lower=None,
                    ci_upper=None,
                    adequate_sample_size=False,
                    finding="insufficient_data",
                )
            )
            continue
        interval = paired_bootstrap(
            candidate,
            baseline,
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            seed=_slice_seed(seed, dimension, slice_name),
        )
        adequate = interval.query_count >= minimum_query_count
        if not adequate:
            finding: Literal["improvement", "regression", "uncertain", "insufficient_data"] = (
                "insufficient_data"
            )
        elif interval.ci_lower > 0:
            finding = "improvement"
        elif interval.ci_upper < 0:
            finding = "regression"
        else:
            finding = "uncertain"
        results.append(
            SliceResult(
                dimension=dimension,
                slice_name=slice_name,
                query_count=interval.query_count,
                excluded_query_count=interval.excluded_query_count,
                candidate_value=fmean(cast(float, candidate[item]) for item in valid),
                baseline_value=fmean(cast(float, baseline[item]) for item in valid),
                point_estimate=interval.point_estimate,
                ci_lower=interval.ci_lower,
                ci_upper=interval.ci_upper,
                adequate_sample_size=adequate,
                finding=finding,
            )
        )
    return results


def select_slice_highlights(results: Sequence[SliceResult]) -> SliceHighlights:
    measured = [result for result in results if result.point_estimate is not None]
    adequate = [result for result in measured if result.adequate_sample_size]
    improvements = [result for result in adequate if cast(float, result.point_estimate) > 0]
    regressions = [result for result in adequate if cast(float, result.point_estimate) < 0]
    uncertain = [result for result in adequate if result.finding == "uncertain"]
    return SliceHighlights(
        strongest_improvement=max(
            improvements,
            key=lambda item: (item.point_estimate, item.dimension, item.slice_name),
            default=None,
        ),
        largest_regression=min(
            regressions,
            key=lambda item: (item.point_estimate, item.dimension, item.slice_name),
            default=None,
        ),
        largest_uncertain_change=max(
            uncertain,
            key=lambda item: (
                abs(cast(float, item.point_estimate)),
                item.dimension,
                item.slice_name,
            ),
            default=None,
        ),
        inadequate_sample_slices=tuple(
            result for result in results if not result.adequate_sample_size
        ),
    )


__all__ = [
    "DEFAULT_MIN_SLICE_QUERIES",
    "LEXICAL_OVERLAP_BOUNDARIES",
    "QUERY_TOKEN_LENGTH_BOUNDARIES",
    "SLICE_DEFINITION_VERSION",
    "TEXT_COMPLETENESS_BOUNDARIES",
    "CandidateSliceFeatures",
    "SliceHighlights",
    "assign_predeclared_slices",
    "brand_presence_bin",
    "candidate_label_composition_bin",
    "evaluate_slices",
    "product_source_bin",
    "product_text_completeness_bin",
    "query_title_lexical_overlap_bin",
    "query_token_length_bin",
    "select_slice_highlights",
    "tokenize_for_slices",
]
