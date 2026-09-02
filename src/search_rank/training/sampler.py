"""Deterministic mixed difficult/random pointwise sampling."""

from __future__ import annotations

import hashlib

import pandas as pd

from search_rank.evaluation.metrics import gain_for


def _stable_key(seed: int, *values: object) -> str:
    return hashlib.sha256("\0".join([str(seed), *map(str, values)]).encode()).hexdigest()


def _ordered_sample(frame: pd.DataFrame, count: int, *, seed: int, salt: str) -> pd.DataFrame:
    if count <= 0 or frame.empty:
        return frame.iloc[0:0].copy()
    values = frame.copy()
    values["_sample_key"] = [
        _stable_key(seed, salt, row.query_id, row.product_id) for row in values.itertuples()
    ]
    values = values.sort_values(["_sample_key", "query_id", "product_id"], kind="mergesort")
    if count <= len(values):
        return values.iloc[:count].drop(columns=["_sample_key"])
    repeated = [values.drop(columns=["_sample_key"])]
    remaining = count - len(values)
    while remaining > 0:
        chunk = values.iloc[: min(remaining, len(values))].drop(columns=["_sample_key"])
        repeated.append(chunk)
        remaining -= len(chunk)
    return pd.concat(repeated, ignore_index=True)


def build_mixed_sample(
    training_frame: pd.DataFrame,
    hard_examples: pd.DataFrame,
    *,
    total_examples: int | None = None,
    hard_fraction: float = 0.5,
    seed: int = 42,
    text_column: str = "text_enriched_v1",
) -> pd.DataFrame:
    if set(training_frame["project_split"].unique()) - {"train"}:
        raise ValueError("mixed sampler accepts training rows only")
    if not 0 <= hard_fraction <= 1:
        raise ValueError("hard_fraction must be between zero and one")
    if text_column not in training_frame:
        raise ValueError(f"missing text column: {text_column}")
    total = total_examples or len(training_frame)
    if total < 1:
        raise ValueError("total_examples must be positive")
    hard_count = round(total * hard_fraction)
    random_count = total - hard_count

    source = training_frame.copy()
    source["query_id"] = source["query_id"].astype(str)
    source["product_id"] = source["product_id"].astype(str)
    if hard_count:
        required_hard = {"query_id", "lower_product_id"}
        if missing := required_hard - set(hard_examples.columns):
            raise ValueError(f"hard examples missing columns: {sorted(missing)}")
        hard_ids = (
            hard_examples[["query_id", "lower_product_id"]]
            .drop_duplicates()
            .rename(columns={"lower_product_id": "product_id"})
        )
        hard_ids["query_id"] = hard_ids["query_id"].astype(str)
        hard_ids["product_id"] = hard_ids["product_id"].astype(str)
        hard_pool = source.merge(hard_ids, on=["query_id", "product_id"], how="inner")
    else:
        hard_pool = source.iloc[0:0].copy()
    if hard_count and hard_pool.empty:
        raise ValueError("hard fraction requested but no hard examples are available")
    hard_sample = _ordered_sample(hard_pool, hard_count, seed=seed, salt="hard")
    hard_sample["sampling_source"] = "difficult"

    random_parts: list[pd.DataFrame] = []
    if random_count:
        source["_grade"] = source["esci_label"].map(gain_for)
        label_groups = sorted(source["_grade"].unique())
        base, remainder = divmod(random_count, len(label_groups))
        for index, grade in enumerate(label_groups):
            count = base + (1 if index < remainder else 0)
            random_parts.append(
                _ordered_sample(
                    source[source["_grade"] == grade],
                    count,
                    seed=seed,
                    salt=f"random-grade-{grade}",
                )
            )
    random_sample = (
        pd.concat(random_parts, ignore_index=True).drop(columns=["_grade"], errors="ignore")
        if random_parts
        else source.iloc[0:0].copy()
    )
    random_sample["sampling_source"] = "stratified_random"
    sample = pd.concat([hard_sample, random_sample], ignore_index=True)
    sample["target"] = sample["esci_label"].map(gain_for).astype(float) / 3.0
    sample["input_text"] = sample[text_column].astype(str)
    sample["_final_key"] = [
        _stable_key(seed, "final", row.query_id, row.product_id, row.sampling_source, index)
        for index, row in enumerate(sample.itertuples())
    ]
    return (
        sample.sort_values("_final_key", kind="mergesort")
        .drop(columns=["_final_key"], errors="ignore")
        .reset_index(drop=True)
    )
