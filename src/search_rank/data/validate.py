"""Fail-closed source validation for the ESCI tables."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .normalize import normalize_text

EXAMPLE_COLUMNS = {
    "example_id",
    "query",
    "query_id",
    "product_id",
    "product_locale",
    "esci_label",
    "small_version",
    "split",
}
PRODUCT_COLUMNS = {
    "product_id",
    "product_locale",
    "product_title",
    "product_description",
    "product_bullet_point",
    "product_brand",
    "product_color",
}
SOURCE_COLUMNS = {"query_id", "source"}
VALID_LABELS = {"E", "S", "C", "I", "Exact", "Substitute", "Complement", "Irrelevant"}
VALID_OFFICIAL_SPLITS = {"train", "test"}


class DataQualityError(ValueError):
    """Raised when source data violates a release-blocking invariant."""


@dataclass
class DataQuality:
    duplicate_rows: int = 0
    conflicting_rows: int = 0
    missing_optional: dict[str, int] = field(default_factory=dict)
    dropped_rows: dict[str, int] = field(default_factory=dict)
    join_missing_products: int = 0
    queries_without_relevant: int = 0


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise DataQualityError(f"{name} schema mismatch; missing columns: {missing}")


def validate_examples(examples: pd.DataFrame) -> DataQuality:
    _require_columns(examples, EXAMPLE_COLUMNS, "examples")
    missing_identifier = examples[["example_id", "query_id", "product_id"]].isna().any(axis=1)
    if missing_identifier.any():
        raise DataQualityError(
            f"missing identifiers in {int(missing_identifier.sum())} example rows"
        )
    empty_queries = examples["query"].map(normalize_text).eq("")
    if empty_queries.any():
        raise DataQualityError(f"empty normalized query in {int(empty_queries.sum())} rows")
    unknown_labels = sorted(set(examples["esci_label"].dropna().astype(str)) - VALID_LABELS)
    if unknown_labels or examples["esci_label"].isna().any():
        raise DataQualityError(f"unknown or missing ESCI labels: {unknown_labels}")
    unknown_splits = sorted(set(examples["split"].dropna().astype(str)) - VALID_OFFICIAL_SPLITS)
    if unknown_splits or examples["split"].isna().any():
        raise DataQualityError(f"unknown or missing official splits: {unknown_splits}")

    keys = ["query_id", "product_locale", "product_id"]
    conflicts = examples.groupby(keys, dropna=False)["esci_label"].nunique().gt(1)
    if conflicts.any():
        raise DataQualityError(
            f"duplicate query-product rows have conflicting labels for {int(conflicts.sum())} keys"
        )
    return DataQuality(duplicate_rows=int(examples.duplicated(keys, keep="first").sum()))


def validate_products(products: pd.DataFrame) -> None:
    _require_columns(products, PRODUCT_COLUMNS, "products")
    missing_identifier = products[["product_id", "product_locale"]].isna().any(axis=1)
    if missing_identifier.any():
        raise DataQualityError(
            f"missing identifiers in {int(missing_identifier.sum())} product rows"
        )
    duplicates = products.duplicated(["product_locale", "product_id"], keep=False)
    if duplicates.any():
        duplicated_rows = products.loc[duplicates].sort_values(["product_locale", "product_id"])
        value_columns = sorted(PRODUCT_COLUMNS - {"product_id", "product_locale"})
        conflicts = (
            duplicated_rows.groupby(["product_locale", "product_id"], dropna=False)[value_columns]
            .nunique(dropna=False)
            .gt(1)
            .any(axis=1)
        )
        if conflicts.any():
            raise DataQualityError(
                f"duplicate product keys have conflicting content for {int(conflicts.sum())} keys"
            )


def validate_sources(sources: pd.DataFrame) -> None:
    _require_columns(sources, SOURCE_COLUMNS, "sources")
    if sources["query_id"].isna().any():
        raise DataQualityError("source table contains missing query_id")
    conflicts = sources.groupby("query_id", dropna=False)["source"].nunique(dropna=False).gt(1)
    if conflicts.any():
        raise DataQualityError(
            f"source table has conflicting rows for {int(conflicts.sum())} queries"
        )


def assert_query_isolation(frame: pd.DataFrame) -> None:
    split_sets = {
        split: set(values.astype(str))
        for split, values in frame.groupby("project_split")["query_id"]
    }
    names = sorted(split_sets)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            overlap = split_sets[left] & split_sets[right]
            if overlap:
                raise DataQualityError(
                    f"query leakage between {left} and {right}: {len(overlap)} identifiers"
                )
