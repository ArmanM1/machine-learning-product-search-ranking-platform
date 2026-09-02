from __future__ import annotations

import pandas as pd
import pytest

from search_rank.baselines.common import ScoredProduct
from search_rank.training.mine_hard_examples import mine_hard_examples
from search_rank.training.sampler import build_mixed_sample


def training_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "query_id": "q1",
                "query": "mug",
                "product_id": "exact",
                "esci_label": "Exact",
                "project_split": "train",
                "text_enriched_v1": "Title: mug",
            },
            {
                "query_id": "q1",
                "query": "mug",
                "product_id": "irrelevant",
                "esci_label": "Irrelevant",
                "project_split": "train",
                "text_enriched_v1": "Title: mug rack",
            },
            {
                "query_id": "q2",
                "query": "shoe",
                "product_id": "substitute",
                "esci_label": "Substitute",
                "project_split": "train",
                "text_enriched_v1": "Title: running shoe",
            },
            {
                "query_id": "q2",
                "query": "shoe",
                "product_id": "complement",
                "esci_label": "Complement",
                "project_split": "train",
                "text_enriched_v1": "Title: shoe laces",
            },
        ]
    )


def baseline_records() -> list[ScoredProduct]:
    return [
        ScoredProduct("q1", "mug", "irrelevant", "bm25", 2, 1, 1, "Irrelevant", 1),
        ScoredProduct("q1", "mug", "exact", "bm25", 1, 2, 0, "Exact", 1),
        ScoredProduct("q2", "shoe", "complement", "bm25", 2, 1, 1, "Complement", 1),
        ScoredProduct("q2", "shoe", "substitute", "bm25", 1, 2, 0, "Substitute", 1),
    ]


def test_mining_finds_baseline_inversions() -> None:
    mined = mine_hard_examples(training_frame(), baseline_records())
    assert set(mined["lower_product_id"]) == {"irrelevant", "complement"}
    assert (mined["score_margin"] > 0).all()


def test_mining_rejects_validation_rows() -> None:
    frame = training_frame()
    frame.loc[0, "project_split"] = "validation"
    with pytest.raises(ValueError, match="training rows only"):
        mine_hard_examples(frame, baseline_records())


def test_mixed_sampler_hits_ratio_and_is_reproducible() -> None:
    mined = mine_hard_examples(training_frame(), baseline_records())
    left = build_mixed_sample(training_frame(), mined, total_examples=8, seed=42)
    right = build_mixed_sample(training_frame().iloc[::-1], mined, total_examples=8, seed=42)
    assert left[["query_id", "product_id", "sampling_source"]].to_dict("records") == right[
        ["query_id", "product_id", "sampling_source"]
    ].to_dict("records")
    assert left["sampling_source"].value_counts().to_dict() == {
        "difficult": 4,
        "stratified_random": 4,
    }
    assert set(left["target"]) == {0.0, 1 / 3, 2 / 3, 1.0}
