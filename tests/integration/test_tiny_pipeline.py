from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from search_rank.artifacts.checksums import sha256_file
from search_rank.baselines.bm25 import rank_bm25
from search_rank.data.io import load_prepared_split
from search_rank.data.prepare import prepare_dataset
from search_rank.data.settings import DataPreparationConfig
from search_rank.data.split import assign_train_validation
from search_rank.evaluation.runner import evaluate_systems, write_evaluation_report
from search_rank.training.sampler import build_mixed_sample

pytestmark = pytest.mark.integration


def _query_for(split: str, *, salt: str) -> str:
    return next(
        f"q{index}"
        for index in range(100)
        if assign_train_validation(f"q{index}", validation_fraction=0.5, salt=salt) == split
    )


def test_tiny_fixture_prepares_ranks_builds_training_rows_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    salt = "tiny-integration-salt"
    train_query = _query_for("train", salt=salt)
    validation_query = _query_for("validation", salt=salt)
    queries = [(train_query, "train"), (validation_query, "train"), ("q-heldout", "test")]
    examples: list[dict[str, object]] = []
    products: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    example_id = 1
    for query_id, official_split in queries:
        sources.append({"query_id": query_id, "source": "tiny-fixture"})
        for suffix, label, title in (
            ("exact", "E", "steel travel mug"),
            ("other", "I", "cotton bath towel"),
        ):
            product_id = f"{query_id}-{suffix}"
            examples.append(
                {
                    "example_id": example_id,
                    "query": "travel mug",
                    "query_id": query_id,
                    "product_id": product_id,
                    "product_locale": "us",
                    "esci_label": label,
                    "small_version": 1,
                    "split": official_split,
                }
            )
            products.append(
                {
                    "product_id": product_id,
                    "product_locale": "us",
                    "product_title": title,
                    "product_description": "small deterministic fixture",
                    "product_bullet_point": "durable",
                    "product_brand": "Fixture",
                    "product_color": "black",
                }
            )
            example_id += 1

    raw = tmp_path / "raw"
    raw.mkdir()
    example_path = raw / "examples.parquet"
    product_path = raw / "products.parquet"
    source_path = raw / "sources.csv"
    pd.DataFrame(examples).to_parquet(example_path, index=False)
    pd.DataFrame(products).to_parquet(product_path, index=False)
    pd.DataFrame(sources).to_csv(source_path, index=False)
    source_files = {"examples": example_path, "products": product_path, "sources": source_path}

    config = DataPreparationConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "dataset_name": "tiny-esci",
            "dataset_version": "fixture-v1",
            "source_revision": "a" * 40,
            "source_url": "https://example.invalid/esci",
            "license_url": "https://example.invalid/license",
            "license_notice_sha256": "b" * 64,
            "locale": "us",
            "small_version": 1,
            "validation_fraction": 0.5,
            "validation_salt": salt,
            "development_query_count": 2,
            "raw_dir": raw,
            "processed_dir": tmp_path / "processed",
            "sources": {
                name: {
                    "url": f"https://example.invalid/{path.name}",
                    "filename": path.name,
                    "sha256": "c" * 64,
                    "size_bytes": max(path.stat().st_size, 1),
                }
                for name, path in source_files.items()
            },
        }
    )
    monkeypatch.setattr("search_rank.data.prepare.acquire_dataset", lambda _: source_files)
    manifest, destination = prepare_dataset(config)
    assert manifest.split_counts["train"].query_count == 1
    assert manifest.split_counts["validation"].query_count == 1

    train, _ = load_prepared_split(destination / "manifest.json", "train")
    validation, _ = load_prepared_split(destination / "manifest.json", "validation")
    assert set(train["query_id"]).isdisjoint(set(validation["query_id"]))
    sample = build_mixed_sample(train, pd.DataFrame(), hard_fraction=0, seed=42)
    assert set(sample["target"]) == {0.0, 1.0}

    baseline = rank_bm25(validation)
    candidate = [replace(record, model_id="candidate-tiny") for record in baseline]
    report = evaluate_systems(
        frame=validation,
        candidate_records=candidate,
        baseline_records={baseline[0].model_id: baseline},
        run_id="run-tiny",
        report_id="report-tiny",
        candidate_model_id="candidate-tiny",
        split="validation",
        test_access_count=0,
        strongest_baseline_id=baseline[0].model_id,
        bootstrap_resamples=20,
        bootstrap_seed=42,
        confidence_level=0.95,
        training_runtime_seconds=0.0,
        training_hardware="local-test-cpu",
        evaluation_hardware="local-test-cpu",
        model_artifact_size_bytes=0,
        clean_run_metric_values=(1.0,),
        clean_runs_match_artifacts=True,
        configuration_frozen=True,
        limitations=["Tiny fixture is integration evidence, not a quality claim."],
    )
    report_path = write_evaluation_report(report, tmp_path / "evaluation-report.json")
    assert report_path.is_file()
    assert report.release_gate_results.decision == "retain_baseline"
    assert report.bootstrap_resamples == 20

    pointer_path = config.processed_dir / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["processed_checksum"] = "sha256:" + "0" * 64
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(ValueError, match="pointer checksum"):
        load_prepared_split(pointer_path, "train")

    manifest_path = destination / "manifest.json"
    original_manifest = manifest_path.read_text(encoding="utf-8")
    semantic_tamper = json.loads(original_manifest)
    semantic_tamper["source_revision"] = "d" * 40
    manifest_path.write_text(json.dumps(semantic_tamper), encoding="utf-8")
    with pytest.raises(ValueError, match=r"semantic manifest|split_manifest_hash"):
        load_prepared_split(manifest_path, "train")
    manifest_path.write_text(original_manifest, encoding="utf-8")

    artifact_path = destination / "train.parquet"
    artifact_path.write_bytes(artifact_path.read_bytes() + b"tamper")
    index_path = destination / "artifact-checksums.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index[artifact_path.name] = f"sha256:{sha256_file(artifact_path)}"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact index"):
        load_prepared_split(destination / "manifest.json", "train")
