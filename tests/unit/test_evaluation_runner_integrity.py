from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from search_rank.baselines.common import ScoredProduct
from search_rank.evaluation.runner import validate_evaluation_inputs


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"query_id": "q1", "product_id": "a", "esci_label": "Exact"},
            {"query_id": "q1", "product_id": "b", "esci_label": "Irrelevant"},
            {"query_id": "q2", "product_id": "c", "esci_label": "Substitute"},
            {"query_id": "q2", "product_id": "d", "esci_label": "Complement"},
        ]
    )


def _records(model_id: str) -> list[ScoredProduct]:
    return [
        ScoredProduct("q1", "mug", "a", model_id, 2.0, 1, 0, "Exact", 0.1),
        ScoredProduct("q1", "mug", "b", model_id, 1.0, 2, 1, "Irrelevant", 0.1),
        ScoredProduct("q2", "shoe", "c", model_id, 2.0, 1, 2, "Substitute", 0.1),
        ScoredProduct("q2", "shoe", "d", model_id, 1.0, 2, 3, "Complement", 0.1),
    ]


def _validate(candidate: list[ScoredProduct], baseline: list[ScoredProduct]) -> None:
    validate_evaluation_inputs(
        frame=_frame(),
        candidate_records=candidate,
        baseline_records={"baseline": baseline},
        candidate_model_id="candidate",
    )


def test_validated_alignment_is_derived_from_authoritative_frame() -> None:
    evidence = validate_evaluation_inputs(
        frame=_frame(),
        candidate_records=_records("candidate"),
        baseline_records={"baseline": list(reversed(_records("baseline")))},
        candidate_model_id="candidate",
    )
    assert evidence.candidate_lists_aligned is True
    assert evidence.authoritative_query_count == 2
    assert evidence.authoritative_row_count == 4


def test_evaluator_rejects_omitted_authoritative_product() -> None:
    with pytest.raises(ValueError, match="does not cover the authoritative frame"):
        _validate(_records("candidate")[:-1], _records("baseline"))


def test_evaluator_rejects_labels_swapped_between_products() -> None:
    candidate = _records("candidate")
    candidate[0] = replace(candidate[0], esci_label="Irrelevant")
    candidate[1] = replace(candidate[1], esci_label="Exact")
    with pytest.raises(ValueError, match="labels differ from the authoritative frame"):
        _validate(candidate, _records("baseline"))


def test_evaluator_rejects_non_finite_score() -> None:
    candidate = _records("candidate")
    candidate[0] = replace(candidate[0], score=float("nan"))
    with pytest.raises(ValueError, match="non-finite score"):
        _validate(candidate, _records("baseline"))


@pytest.mark.parametrize("ranks", [(1, 1), (1, 3)])
def test_evaluator_rejects_non_unique_or_non_contiguous_ranks(
    ranks: tuple[int, int],
) -> None:
    candidate = _records("candidate")
    candidate[0] = replace(candidate[0], rank=ranks[0])
    candidate[1] = replace(candidate[1], rank=ranks[1])
    with pytest.raises(ValueError, match="unique and contiguous"):
        _validate(candidate, _records("baseline"))


def test_evaluator_rejects_unexpected_record_model_id() -> None:
    candidate = _records("candidate")
    candidate[0] = replace(candidate[0], model_id="other")
    with pytest.raises(ValueError, match="contains record for model"):
        _validate(candidate, _records("baseline"))
