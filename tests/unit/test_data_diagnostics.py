from __future__ import annotations

import pandas as pd

from search_rank.data.prepare import _transform
from search_rank.data.settings import DataPreparationConfig
from search_rank.data.split import assign_train_validation


def _query_for(split: str, *, salt: str) -> str:
    return next(
        f"q{index}"
        for index in range(100)
        if assign_train_validation(f"q{index}", validation_fraction=0.5, salt=salt) == split
    )


def test_optional_and_label_diagnostics_never_inspect_heldout_rows() -> None:
    salt = "diagnostic-scope-salt"
    query_ids = [_query_for("train", salt=salt), _query_for("validation", salt=salt), "heldout"]
    labels = ["E", "I", "S"]
    splits = ["train", "train", "test"]
    examples = pd.DataFrame(
        [
            {
                "example_id": index,
                "query": "fixture query",
                "query_id": query_id,
                "product_id": f"p{index}",
                "product_locale": "us",
                "esci_label": label,
                "small_version": 1,
                "split": split,
            }
            for index, (query_id, label, split) in enumerate(
                zip(query_ids, labels, splits, strict=True), start=1
            )
        ]
    )
    products = pd.DataFrame(
        [
            {
                "product_id": f"p{index}",
                "product_locale": "us",
                "product_title": "Fixture",
                "product_description": None if index == 3 else "description",
                "product_bullet_point": "bullet",
                "product_brand": None if index >= 2 else "brand",
                "product_color": "black",
            }
            for index in range(1, 4)
        ]
    )
    sources = pd.DataFrame([{"query_id": query_id, "source": "fixture"} for query_id in query_ids])
    config = DataPreparationConfig.model_construct(
        validation_fraction=0.5,
        validation_salt=salt,
    )

    _, report = _transform(examples, products, sources, config)

    assert report["label_distribution"] == {"Exact": 1, "Irrelevant": 1}
    assert report["missing_optional_fields"]["product_brand"] == 1
    assert report["missing_optional_fields"]["product_description"] == 0
    assert report["label_diagnostics_scope"] == "train_and_validation_only"
    assert report["optional_diagnostics_scope"] == "train_and_validation_only"
