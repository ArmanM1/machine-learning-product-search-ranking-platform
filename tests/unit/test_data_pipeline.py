from __future__ import annotations

import pandas as pd
import pytest

from search_rank.data.normalize import normalize_text
from search_rank.data.split import assign_train_validation, development_query_ids, sorted_id_hash
from search_rank.data.validate import DataQualityError, assert_query_isolation, validate_examples
from search_rank.features.product_text import render_product_text


def test_normalization_is_conservative_and_deterministic() -> None:
    assert normalize_text("  A\tproduct\nname  ") == "A product name"
    assert normalize_text("\uff45\uff58\uff41\uff43\uff54") == "exact"
    assert normalize_text(None) == ""
    assert normalize_text(float("nan")) == ""


def test_product_templates_never_include_labels() -> None:
    row = {
        "product_title": "Travel mug",
        "product_brand": "North",
        "product_bullet_point": None,
        "product_description": "Keeps drinks warm",
        "esci_label": "Exact",
    }
    assert render_product_text(row, "title_v1") == "Travel mug"
    enriched = render_product_text(row, "enriched_v1")
    assert enriched == "Title: Travel mug\nBrand: North\nDescription: Keeps drinks warm"
    assert "Exact" not in enriched


def test_query_split_and_development_sample_are_order_independent() -> None:
    query_ids = [str(value) for value in range(1000)]
    left = {
        query_id: assign_train_validation(query_id, validation_fraction=0.1, salt="stable-salt-v1")
        for query_id in query_ids
    }
    right = {
        query_id: assign_train_validation(query_id, validation_fraction=0.1, salt="stable-salt-v1")
        for query_id in reversed(query_ids)
    }
    assert left == right
    assert development_query_ids(query_ids, count=20, salt="dev-salt-v1") == (
        development_query_ids(reversed(query_ids), count=20, salt="dev-salt-v1")
    )
    assert sorted_id_hash(query_ids) == sorted_id_hash(reversed(query_ids))


def test_conflicting_duplicate_labels_fail() -> None:
    frame = pd.DataFrame(
        [
            {
                "example_id": 1,
                "query": "mug",
                "query_id": 10,
                "product_id": "A",
                "product_locale": "us",
                "esci_label": "E",
                "small_version": 1,
                "split": "train",
            },
            {
                "example_id": 2,
                "query": "mug",
                "query_id": 10,
                "product_id": "A",
                "product_locale": "us",
                "esci_label": "I",
                "small_version": 1,
                "split": "train",
            },
        ]
    )
    with pytest.raises(DataQualityError, match="conflicting labels"):
        validate_examples(frame)


def test_query_overlap_fails() -> None:
    frame = pd.DataFrame({"query_id": ["q1", "q1"], "project_split": ["train", "validation"]})
    with pytest.raises(DataQualityError, match="query leakage"):
        assert_query_isolation(frame)
