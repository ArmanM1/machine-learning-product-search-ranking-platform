"""Deterministic example selection for balanced win/loss reporting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from search_rank.schemas.evaluation import HELDOUT_REQUIRED_EXAMPLE_COUNTS, ExampleResult

REQUIRED_WIN_COUNT = HELDOUT_REQUIRED_EXAMPLE_COUNTS["win"]
REQUIRED_LOSS_COUNT = HELDOUT_REQUIRED_EXAMPLE_COUNTS["loss"]
REQUIRED_UNCERTAIN_COUNT = HELDOUT_REQUIRED_EXAMPLE_COUNTS["tie_or_uncertain"]


class RepresentativeExampleSelectionError(ValueError):
    """Raised when candidate evidence cannot satisfy the frozen example quotas."""


@dataclass(frozen=True)
class ExampleCandidate:
    query_id: str
    baseline_metric: float
    candidate_metric: float
    public_product_ids: tuple[str, ...] = ()
    lexical_preferred: bool = False
    lexical_baseline_metric: float | None = None
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
    *,
    baseline_metric: float | None = None,
) -> ExampleResult:
    selected_baseline = item.baseline_metric if baseline_metric is None else baseline_metric
    return ExampleResult(
        query_id=item.query_id,
        category=category,
        baseline_metric=selected_baseline,
        candidate_metric=item.candidate_metric,
        delta=item.candidate_metric - selected_baseline,
        selection_rule=selection_rule,
        public_product_ids=list(item.public_product_ids),
        notes=item.notes,
    )


def select_representative_examples(
    candidates: Sequence[ExampleCandidate],
    *,
    win_count: int = REQUIRED_WIN_COUNT,
    loss_count: int = REQUIRED_LOSS_COUNT,
    uncertain_count: int = REQUIRED_UNCERTAIN_COUNT,
    tie_tolerance: float = 1e-12,
    require_complete: bool = True,
) -> list[ExampleResult]:
    """Select examples by frozen metric rules, then query ID for stable ties.

    A complete selection is fail-closed: it contains every requested win, loss,
    and tie/uncertain example plus the two predeclared failure categories. The
    caller may opt out only for non-held-out exploratory evaluation.
    """

    if min(win_count, loss_count, uncertain_count) < 0:
        raise ValueError("example counts cannot be negative")
    if tie_tolerance < 0:
        raise ValueError("tie_tolerance cannot be negative")
    query_ids = [item.query_id for item in candidates]
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("representative-example candidates must have unique query IDs")
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
        key=lambda item: (
            item.candidate_metric
            - (
                item.lexical_baseline_metric
                if item.lexical_baseline_metric is not None
                else item.baseline_metric
            ),
            item.query_id,
        ),
        default=None,
    )
    if lexical is not None:
        results.append(
            _to_result(
                lexical,
                "lexical_preferred",
                "most negative delta among examples marked by the frozen lexical-preferred rule",
                baseline_metric=lexical.lexical_baseline_metric,
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
    if require_complete:
        shortages = []
        required_and_available = (
            ("win", win_count, len(wins)),
            ("loss", loss_count, len(losses)),
            ("tie_or_uncertain", uncertain_count, len(uncertain)),
            ("lexical_preferred", 1, int(lexical is not None)),
            ("complement_exact_confusion", 1, int(confusion is not None)),
        )
        for category, required, available in required_and_available:
            if available < required:
                shortages.append(f"{category} required={required} available={available}")
        if shortages:
            detail = "; ".join(shortages)
            raise RepresentativeExampleSelectionError(
                "representative-example requirements cannot be satisfied: " + detail
            )
    return results


__all__ = [
    "REQUIRED_LOSS_COUNT",
    "REQUIRED_UNCERTAIN_COUNT",
    "REQUIRED_WIN_COUNT",
    "ExampleCandidate",
    "RepresentativeExampleSelectionError",
    "select_representative_examples",
]
