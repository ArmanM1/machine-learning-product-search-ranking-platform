"""Deterministic example selection for balanced win/loss reporting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from search_rank.schemas.evaluation import ExampleResult


@dataclass(frozen=True)
class ExampleCandidate:
    query_id: str
    baseline_metric: float
    candidate_metric: float
    public_product_ids: tuple[str, ...] = ()
    lexical_preferred: bool = False
    complement_exact_confusion: bool = False
    notes: str | None = None

    @property
    def delta(self) -> float:
        return self.candidate_metric - self.baseline_metric


def _to_result(
    item: ExampleCandidate,
    category: Literal[
        "win",
        "loss",
        "tie_or_uncertain",
        "lexical_preferred",
        "complement_exact_confusion",
    ],
    selection_rule: str,
) -> ExampleResult:
    return ExampleResult(
        query_id=item.query_id,
        category=category,
        baseline_metric=item.baseline_metric,
        candidate_metric=item.candidate_metric,
        delta=item.delta,
        selection_rule=selection_rule,
        public_product_ids=list(item.public_product_ids),
        notes=item.notes,
    )


def select_representative_examples(
    candidates: Sequence[ExampleCandidate],
    *,
    win_count: int = 5,
    loss_count: int = 5,
    uncertain_count: int = 3,
    tie_tolerance: float = 1e-12,
) -> list[ExampleResult]:
    """Select examples by frozen metric rules, then query ID for stable ties."""

    if min(win_count, loss_count, uncertain_count) < 0:
        raise ValueError("example counts cannot be negative")
    wins = sorted(
        (item for item in candidates if item.delta > tie_tolerance),
        key=lambda item: (-item.delta, item.query_id),
    )[:win_count]
    losses = sorted(
        (item for item in candidates if item.delta < -tie_tolerance),
        key=lambda item: (item.delta, item.query_id),
    )[:loss_count]
    uncertain = sorted(
        (item for item in candidates if abs(item.delta) <= tie_tolerance),
        key=lambda item: (abs(item.delta), item.query_id),
    )[:uncertain_count]

    results = [
        *(
            _to_result(
                item,
                "win",
                "largest positive candidate-minus-baseline primary-metric delta; query-ID tie break",
            )
            for item in wins
        ),
        *(
            _to_result(
                item,
                "loss",
                "largest negative candidate-minus-baseline primary-metric delta; query-ID tie break",
            )
            for item in losses
        ),
        *(
            _to_result(
                item,
                "tie_or_uncertain",
                f"absolute primary-metric delta <= {tie_tolerance}; query-ID tie break",
            )
            for item in uncertain
        ),
    ]

    lexical = min(
        (item for item in candidates if item.lexical_preferred),
        key=lambda item: (item.delta, item.query_id),
        default=None,
    )
    if lexical is not None:
        results.append(
            _to_result(
                lexical,
                "lexical_preferred",
                "most negative delta among examples marked by the frozen lexical-preferred rule",
            )
        )
    confusion = min(
        (item for item in candidates if item.complement_exact_confusion),
        key=lambda item: (item.delta, item.query_id),
        default=None,
    )
    if confusion is not None:
        results.append(
            _to_result(
                confusion,
                "complement_exact_confusion",
                "most negative delta among automatically detected Complement-versus-Exact inversions",
            )
        )
    return results


__all__ = ["ExampleCandidate", "select_representative_examples"]
