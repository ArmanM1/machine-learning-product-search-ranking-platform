"""Exact, dependency-free ranking metrics for the project relevance contract.

All metrics operate on a *single query's supplied candidate list* unless the
function name says ``macro``.  Inputs are in predicted rank order.  This keeps
the evaluator independent of any particular model library and makes it hard to
accidentally bootstrap individual product rows.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean
from typing import TypeAlias


class RelevanceLabel(StrEnum):
    EXACT = "Exact"
    SUBSTITUTE = "Substitute"
    COMPLEMENT = "Complement"
    IRRELEVANT = "Irrelevant"


RELEVANCE_MAPPING_VERSION = "project_graded_v1"
RELEVANCE_GAINS: Mapping[RelevanceLabel, int] = {
    RelevanceLabel.EXACT: 3,
    RelevanceLabel.SUBSTITUTE: 2,
    RelevanceLabel.COMPLEMENT: 1,
    RelevanceLabel.IRRELEVANT: 0,
}

Relevance: TypeAlias = RelevanceLabel | str | int

_STRING_TO_LABEL = {
    "e": RelevanceLabel.EXACT,
    "exact": RelevanceLabel.EXACT,
    "s": RelevanceLabel.SUBSTITUTE,
    "substitute": RelevanceLabel.SUBSTITUTE,
    "c": RelevanceLabel.COMPLEMENT,
    "complement": RelevanceLabel.COMPLEMENT,
    "i": RelevanceLabel.IRRELEVANT,
    "irrelevant": RelevanceLabel.IRRELEVANT,
}


class RankingAlignmentError(ValueError):
    """Raised when systems did not score identical query/candidate universes."""


@dataclass(frozen=True)
class QueryMetrics:
    graded_ndcg_at_10: float | None
    exact_mrr_at_10: float
    recall_exact_or_substitute_at_10: float
    pairwise_ordinal_accuracy: float | None
    graded_ndcg_at_5: float | None
    exact_top_1_rate: float

    def as_dict(self) -> dict[str, float | None]:
        return {
            "graded_ndcg@10": self.graded_ndcg_at_10,
            "exact_mrr@10": self.exact_mrr_at_10,
            "recall_exact_or_substitute@10": self.recall_exact_or_substitute_at_10,
            "pairwise_ordinal_accuracy": self.pairwise_ordinal_accuracy,
            "graded_ndcg@5": self.graded_ndcg_at_5,
            "exact_top_1_rate": self.exact_top_1_rate,
        }

    def __getitem__(self, name: str) -> float | None:
        return self.as_dict()[name]


@dataclass(frozen=True)
class AggregateMetric:
    value: float | None
    query_count: int
    excluded_query_count: int
    per_query: Mapping[str, float | None]


@dataclass(frozen=True)
class AggregateMetrics:
    values: Mapping[str, float | None]
    metric_query_counts: Mapping[str, int]
    metric_excluded_query_counts: Mapping[str, int]
    per_query: Mapping[str, QueryMetrics]


def gain_for(relevance: Relevance) -> int:
    """Return the project-defined ordinal gain (3/2/1/0)."""

    if isinstance(relevance, bool):
        raise TypeError("boolean is not a valid relevance grade")
    if isinstance(relevance, int):
        if relevance not in (0, 1, 2, 3):
            raise ValueError(f"unknown relevance gain: {relevance!r}")
        return relevance
    if isinstance(relevance, RelevanceLabel):
        return RELEVANCE_GAINS[relevance]
    if isinstance(relevance, str):
        try:
            return RELEVANCE_GAINS[_STRING_TO_LABEL[relevance.strip().casefold()]]
        except KeyError as exc:
            raise ValueError(f"unknown relevance label: {relevance!r}") from exc
    raise TypeError(f"unsupported relevance value: {type(relevance).__name__}")


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")


def _gains(relevances: Iterable[Relevance]) -> list[int]:
    return [gain_for(relevance) for relevance in relevances]


def dcg_at_k(relevances: Sequence[Relevance], k: int = 10) -> float:
    """Compute DCG using the declared gains directly (not ``2**gain - 1``)."""

    _validate_k(k)
    return math.fsum(
        gain_for(relevance) / math.log2(rank + 1)
        for rank, relevance in enumerate(relevances[:k], start=1)
    )


def ndcg_at_k(relevances: Sequence[Relevance], k: int = 10) -> float | None:
    """Compute within-query nDCG, returning ``None`` for zero-ideal queries."""

    _validate_k(k)
    gains = _gains(relevances)
    ideal_dcg = dcg_at_k(sorted(gains, reverse=True), k)
    if ideal_dcg == 0.0:
        return None
    return dcg_at_k(gains, k) / ideal_dcg


def exact_mrr_at_k(relevances: Sequence[Relevance], k: int = 10) -> float:
    """Reciprocal rank of the first Exact item, or zero when none is in top-k."""

    _validate_k(k)
    for rank, relevance in enumerate(relevances[:k], start=1):
        if gain_for(relevance) == 3:
            return 1.0 / rank
    return 0.0


def recall_at_k(
    relevances: Sequence[Relevance],
    k: int = 10,
    *,
    minimum_relevant_gain: int = 2,
) -> float:
    """Recall for Exact or Substitute by default.

    A query with no eligible relevant item has recall zero.  It is not excluded
    from the primary nDCG count unless its ideal DCG is also zero.
    """

    _validate_k(k)
    if minimum_relevant_gain not in (1, 2, 3):
        raise ValueError("minimum_relevant_gain must be 1, 2, or 3")
    gains = _gains(relevances)
    relevant_total = sum(gain >= minimum_relevant_gain for gain in gains)
    if relevant_total == 0:
        return 0.0
    retrieved = sum(gain >= minimum_relevant_gain for gain in gains[:k])
    return retrieved / relevant_total


def recall_exact_or_substitute_at_k(relevances: Sequence[Relevance], k: int = 10) -> float:
    return recall_at_k(relevances, k, minimum_relevant_gain=2)


def pairwise_ordinal_accuracy(
    relevances: Sequence[Relevance],
    scores: Sequence[float] | None = None,
) -> float | None:
    """Accuracy over every pair with unequal grades.

    With no ``scores``, ``relevances`` must already be in predicted rank order.
    If raw model scores are supplied, a score tie receives half credit.  Pairs
    with equal ground-truth grade are excluded.  ``None`` denotes a query with
    no comparable pairs.
    """

    gains = _gains(relevances)
    if scores is not None:
        if len(scores) != len(gains):
            raise ValueError("scores and relevances must have equal length")
        numeric_scores = []
        for score in scores:
            numeric = float(score)
            if not math.isfinite(numeric):
                raise ValueError("scores must be finite")
            numeric_scores.append(numeric)
    else:
        numeric_scores = None

    credit = 0.0
    comparable = 0
    for left in range(len(gains)):
        for right in range(left + 1, len(gains)):
            if gains[left] == gains[right]:
                continue
            comparable += 1
            if numeric_scores is None:
                if gains[left] > gains[right]:
                    credit += 1.0
                continue
            grade_direction = gains[left] - gains[right]
            score_direction = numeric_scores[left] - numeric_scores[right]
            if score_direction == 0:
                credit += 0.5
            elif grade_direction * score_direction > 0:
                credit += 1.0
    if comparable == 0:
        return None
    return credit / comparable


def exact_top_1_rate(relevances: Sequence[Relevance]) -> float:
    return float(bool(relevances) and gain_for(relevances[0]) == 3)


def evaluate_query(relevances: Sequence[Relevance]) -> QueryMetrics:
    """Compute the preregistered primary and every required secondary metric."""

    return QueryMetrics(
        graded_ndcg_at_10=ndcg_at_k(relevances, 10),
        exact_mrr_at_10=exact_mrr_at_k(relevances, 10),
        recall_exact_or_substitute_at_10=recall_exact_or_substitute_at_k(relevances, 10),
        pairwise_ordinal_accuracy=pairwise_ordinal_accuracy(relevances),
        graded_ndcg_at_5=ndcg_at_k(relevances, 5),
        exact_top_1_rate=exact_top_1_rate(relevances),
    )


def macro_metric(
    per_query: Mapping[str, float | None],
) -> AggregateMetric:
    """Macro-average query values and report explicit exclusions."""

    included: list[float] = []
    for query_id, value in per_query.items():
        if not str(query_id):
            raise ValueError("query IDs must be non-empty")
        if value is None:
            continue
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"non-finite metric for query {query_id!r}")
        included.append(numeric)
    return AggregateMetric(
        value=fmean(included) if included else None,
        query_count=len(included),
        excluded_query_count=len(per_query) - len(included),
        per_query=dict(per_query),
    )


def aggregate_query_metrics(
    rankings: Mapping[str, Sequence[Relevance]],
) -> AggregateMetrics:
    per_query = {str(query_id): evaluate_query(labels) for query_id, labels in rankings.items()}
    metric_names = (
        tuple(next(iter(per_query.values())).as_dict())
        if per_query
        else (
            "graded_ndcg@10",
            "exact_mrr@10",
            "recall_exact_or_substitute@10",
            "pairwise_ordinal_accuracy",
            "graded_ndcg@5",
            "exact_top_1_rate",
        )
    )
    values: dict[str, float | None] = {}
    counts: dict[str, int] = {}
    excluded: dict[str, int] = {}
    for name in metric_names:
        aggregate = macro_metric({query_id: result[name] for query_id, result in per_query.items()})
        values[name] = aggregate.value
        counts[name] = aggregate.query_count
        excluded[name] = aggregate.excluded_query_count
    return AggregateMetrics(values, counts, excluded, per_query)


def rank_by_score(product_ids: Sequence[str], scores: Sequence[float]) -> list[int]:
    """Return source indices sorted by descending score then product ID."""

    if len(product_ids) != len(scores):
        raise ValueError("product_ids and scores must have equal length")
    if len(set(product_ids)) != len(product_ids):
        raise ValueError("product_ids must be unique within a query")
    checked: list[float] = []
    for score in scores:
        numeric = float(score)
        if not math.isfinite(numeric):
            raise ValueError("scores must be finite")
        checked.append(numeric)
    return sorted(range(len(product_ids)), key=lambda index: (-checked[index], product_ids[index]))


def validate_ranking_alignment(
    candidate: Mapping[str, Sequence[str]],
    baseline: Mapping[str, Sequence[str]],
) -> None:
    """Require identical queries and candidate products across two systems."""

    candidate_queries = set(candidate)
    baseline_queries = set(baseline)
    if candidate_queries != baseline_queries:
        missing_candidate = sorted(baseline_queries - candidate_queries)
        missing_baseline = sorted(candidate_queries - baseline_queries)
        raise RankingAlignmentError(
            "query mismatch; "
            f"missing from candidate={missing_candidate}, missing from baseline={missing_baseline}"
        )
    for query_id in sorted(candidate_queries):
        candidate_ids = list(candidate[query_id])
        baseline_ids = list(baseline[query_id])
        if len(candidate_ids) != len(set(candidate_ids)):
            raise RankingAlignmentError(f"candidate has duplicate products for query {query_id!r}")
        if len(baseline_ids) != len(set(baseline_ids)):
            raise RankingAlignmentError(f"baseline has duplicate products for query {query_id!r}")
        if set(candidate_ids) != set(baseline_ids):
            raise RankingAlignmentError(
                f"candidate-product mismatch for query {query_id!r}: "
                f"candidate_only={sorted(set(candidate_ids) - set(baseline_ids))}, "
                f"baseline_only={sorted(set(baseline_ids) - set(candidate_ids))}"
            )


# Familiar short aliases, while canonical names remain explicit in reports.
mrr_at_k = exact_mrr_at_k
graded_ndcg_at_k = ndcg_at_k
exact_or_substitute_recall_at_k = recall_exact_or_substitute_at_k
pairwise_accuracy = pairwise_ordinal_accuracy

__all__ = [
    "RELEVANCE_GAINS",
    "RELEVANCE_MAPPING_VERSION",
    "AggregateMetric",
    "AggregateMetrics",
    "QueryMetrics",
    "RankingAlignmentError",
    "RelevanceLabel",
    "aggregate_query_metrics",
    "dcg_at_k",
    "evaluate_query",
    "exact_mrr_at_k",
    "exact_or_substitute_recall_at_k",
    "exact_top_1_rate",
    "gain_for",
    "graded_ndcg_at_k",
    "macro_metric",
    "mrr_at_k",
    "ndcg_at_k",
    "pairwise_accuracy",
    "pairwise_ordinal_accuracy",
    "rank_by_score",
    "recall_at_k",
    "recall_exact_or_substitute_at_k",
    "validate_ranking_alignment",
]
