"""Deterministic, query-isolated ESCI preparation pipeline."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from search_rank.artifacts.checksums import sha256_file
from search_rank.config import sha256_value
from search_rank.features.product_text import render_product_text
from search_rank.logging import log_event
from search_rank.schemas.dataset import DatasetManifest, SplitCounts

from .download import acquire_dataset
from .normalize import NORMALIZATION_VERSION, normalize_text
from .settings import DataPreparationConfig
from .split import assign_train_validation, development_query_ids, sorted_id_hash
from .validate import (
    DataQualityError,
    assert_query_isolation,
    validate_examples,
    validate_products,
    validate_sources,
)

LOGGER = logging.getLogger(__name__)
PREPROCESSING_VERSION = f"esci_prepare_v1+{NORMALIZATION_VERSION}"
LABEL_NAMES = {"E": "Exact", "S": "Substitute", "C": "Complement", "I": "Irrelevant"}


def _read_sources(
    paths: dict[str, Path], config: DataPreparationConfig
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    example_columns = [
        "example_id",
        "query",
        "query_id",
        "product_id",
        "product_locale",
        "esci_label",
        "small_version",
        "split",
    ]
    examples_table = pq.read_table(
        paths["examples"],
        columns=example_columns,
        filters=[
            ("product_locale", "=", config.locale),
            ("small_version", "=", config.small_version),
        ],
    )
    examples = examples_table.to_pandas()
    product_ids = set(examples["product_id"].astype(str))

    product_columns = [
        "product_id",
        "product_locale",
        "product_title",
        "product_description",
        "product_bullet_point",
        "product_brand",
        "product_color",
    ]
    product_table = pq.read_table(
        paths["products"],
        columns=product_columns,
        filters=[("product_locale", "=", config.locale)],
    )
    products = product_table.to_pandas()
    products = products[products["product_id"].astype(str).isin(product_ids)].copy()
    sources = pd.read_csv(paths["sources"], usecols=["query_id", "source"])
    sources = sources[
        sources["query_id"].astype(str).isin(set(examples["query_id"].astype(str)))
    ].copy()
    return examples, products, sources


def _transform(
    examples: pd.DataFrame,
    products: pd.DataFrame,
    sources: pd.DataFrame,
    config: DataPreparationConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    quality = validate_examples(examples)
    validate_products(products)
    validate_sources(sources)

    keys = ["product_locale", "product_id"]
    examples = examples.drop_duplicates(["query_id", *keys], keep="first").copy()
    products = products.drop_duplicates(keys, keep="first").copy()
    sources = sources.drop_duplicates(["query_id"], keep="first").rename(
        columns={"source": "product_source"}
    )

    merged = examples.merge(products, how="left", on=keys, validate="many_to_one", indicator=True)
    missing_products = int(merged["_merge"].ne("both").sum())
    if missing_products:
        raise DataQualityError(f"product join lost {missing_products} rows")
    merged = merged.drop(columns=["_merge"]).merge(
        sources, how="left", on="query_id", validate="many_to_one"
    )

    merged["query"] = merged["query"].map(normalize_text)
    optional_fields = [
        "product_title",
        "product_brand",
        "product_bullet_point",
        "product_description",
        "product_color",
        "product_source",
    ]
    for field in optional_fields:
        merged[f"{field}_present"] = merged[field].map(normalize_text).ne("")
        merged[field] = merged[field].map(normalize_text)

    merged["esci_label"] = (
        merged["esci_label"].astype(str).map(lambda value: LABEL_NAMES.get(value, value))
    )
    merged["source_index"] = merged["example_id"].astype("int64")
    merged["official_split"] = merged["split"].astype(str)
    merged["project_split"] = merged.apply(
        lambda row: (
            "test"
            if row["official_split"] == "test"
            else assign_train_validation(
                row["query_id"],
                validation_fraction=config.validation_fraction,
                salt=config.validation_salt,
            )
        ),
        axis=1,
    )
    merged["text_title_v1"] = merged.apply(lambda row: render_product_text(row, "title_v1"), axis=1)
    merged["text_enriched_v1"] = merged.apply(
        lambda row: render_product_text(row, "enriched_v1"), axis=1
    )
    assert_query_isolation(merged)

    merged = merged.sort_values(
        ["project_split", "query_id", "source_index", "product_id"], kind="mergesort"
    ).reset_index(drop=True)
    development_rows = merged[merged["project_split"] != "test"]
    missingness = {
        field: int((~development_rows[f"{field}_present"]).sum()) for field in optional_fields
    }
    relevant = development_rows["esci_label"].isin(["Exact", "Substitute", "Complement"])
    no_relevant = int((~relevant.groupby(development_rows["query_id"]).any()).sum())
    report = {
        "duplicate_rows_dropped": quality.duplicate_rows,
        "join_missing_products": missing_products,
        "missing_optional_fields": missingness,
        "queries_without_relevant_candidates": no_relevant,
        "label_distribution": dict(Counter(development_rows["esci_label"].astype(str))),
        "label_diagnostics_scope": "train_and_validation_only",
        "optional_diagnostics_scope": "train_and_validation_only",
    }
    return merged, report


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(
        table,
        path,
        compression="zstd",
        compression_level=9,
        use_dictionary=True,
        write_statistics=True,
        data_page_version="2.0",
    )


def _prefixed(value: str) -> str:
    return f"sha256:{value}"


def _publish_directory(staging: Path, destination: Path) -> None:
    """Atomically publish, tolerating brief Windows indexer locks."""

    for attempt in range(6):
        try:
            os.replace(staging, destination)
            return
        except PermissionError:
            if destination.exists():
                shutil.rmtree(staging)
                return
            if attempt == 5:
                raise
            time.sleep(0.2 * (attempt + 1))


def prepare_dataset(config: DataPreparationConfig) -> tuple[DatasetManifest, Path]:
    paths = acquire_dataset(config)
    examples, products, sources = _read_sources(paths, config)
    frame, quality = _transform(examples, products, sources, config)
    config.processed_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="prepare-", dir=config.processed_dir))
    try:
        artifact_checksums: dict[str, str] = {}
        split_counts: dict[str, SplitCounts] = {}
        split_query_hashes: dict[str, str] = {}
        for split in ("train", "validation", "test"):
            split_frame = frame[frame["project_split"] == split].copy()
            path = staging / f"{split}.parquet"
            _write_parquet(split_frame, path)
            artifact_checksums[path.name] = sha256_file(path)
            split_counts[split] = SplitCounts(
                query_count=int(split_frame["query_id"].nunique()),
                row_count=len(split_frame),
                product_count=int(split_frame["product_id"].nunique()),
            )
            split_query_hashes[split] = _prefixed(sorted_id_hash(split_frame["query_id"]))

        development_ids = development_query_ids(
            frame[frame["project_split"].isin(["train", "validation"])]["query_id"],
            count=config.development_query_count,
            salt=f"{config.validation_salt}:development",
        )
        development = frame[frame["query_id"].astype(str).isin(development_ids)].copy()
        development_path = staging / "development.parquet"
        _write_parquet(development, development_path)
        artifact_checksums[development_path.name] = sha256_file(development_path)

        quality_path = staging / "data-quality.json"
        quality_path.write_text(
            json.dumps(quality, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        artifact_checksums[quality_path.name] = sha256_file(quality_path)
        processed_hash = sha256_value(
            {
                "preprocessing_version": PREPROCESSING_VERSION,
                "artifacts": artifact_checksums,
            }
        )
        destination = config.processed_dir / processed_hash
        manifest = DatasetManifest(
            schema_version="1.0.0",
            dataset_name=config.dataset_name,
            dataset_version=config.dataset_version,
            source_url=str(config.source_url),
            source_revision=config.source_revision,
            license_url=str(config.license_url),
            license_notice_hash=_prefixed(config.license_notice_sha256),
            task="query-product-reranking",
            locale=config.locale,
            raw_checksums={
                name: _prefixed(source.sha256) for name, source in config.sources.items()
            },
            preprocessing_version=PREPROCESSING_VERSION,
            split_strategy=(
                f"official train/test; training query SHA-256 split with "
                f"{config.validation_fraction:.4f} validation fraction"
            ),
            split_salt_hash=_prefixed(sha256_value(config.validation_salt)),
            split_counts=split_counts,
            split_query_id_hashes=split_query_hashes,
            row_count=len(frame),
            query_count=int(frame["query_id"].nunique()),
            product_count=int(frame["product_id"].nunique()),
            label_distribution={
                str(key): int(value) for key, value in quality["label_distribution"].items()
            },
            missingness={
                str(key): int(value) for key, value in quality["missing_optional_fields"].items()
            },
            dropped_rows={"duplicate_rows": int(quality["duplicate_rows_dropped"])},
            processed_artifact_uri=f"artifact://{config.dataset_name}/{processed_hash}",
            processed_checksum=_prefixed(processed_hash),
            created_at=datetime.now(UTC),
        )
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "artifact-checksums.json").write_text(
            json.dumps(
                {name: _prefixed(value) for name, value in artifact_checksums.items()},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            shutil.rmtree(staging)
        else:
            _publish_directory(staging, destination)
        pointer = config.processed_dir / "current.json"
        pointer.write_text(
            json.dumps(
                {
                    "processed_checksum": _prefixed(processed_hash),
                    "manifest": f"{processed_hash}/manifest.json",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        log_event(LOGGER, "dataset_prepared", checksum=processed_hash, rows=len(frame))
        return manifest, destination
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
