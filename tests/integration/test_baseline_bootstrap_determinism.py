from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from search_rank.artifacts.checksums import sha256_file
from search_rank.cli import bootstrap_baseline_release
from search_rank.command_config import BaselineRunConfig
from search_rank.config import sha256_value, validate_config
from search_rank.serving.query_store import CuratedProduct, CuratedQuery, write_curated_queries

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/experiments/baselines-v1.yaml"
DATASET_HASH = "sha256:" + "a" * 64
SPLIT_HASH = "sha256:" + "b" * 64
IMAGE_DIGEST = "sha256:" + "c" * 64
GIT_SHA = "d" * 40
ENDED_AT = "2026-09-02T00:01:00Z"


def _query(candidate_count: int) -> CuratedQuery:
    return CuratedQuery(
        query_id=f"q-{candidate_count}",
        query=f"query with {candidate_count} candidates",
        products=tuple(
            CuratedProduct(
                product_id=f"p-{candidate_count}-{index}",
                title=f"Product {index}",
                text=f"Product {index} text",
                esci_label=None,
            )
            for index in range(candidate_count)
        ),
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    config_hash = f"sha256:{sha256_value(validate_config(CONFIG_PATH, BaselineRunConfig))}"
    model_ids = ("bm25-enriched-v1", "bm25-title-v1")
    baseline = {
        "schema_version": "1.0.0",
        "config_hash": config_hash,
        "dataset_manifest_hash": DATASET_HASH,
        "dataset_name": "fixture",
        "dataset_version": "v1",
        "dataset_locale": "us",
        "split": "validation",
        "metrics": {model_ids[0]: 0.7, model_ids[1]: 0.6},
        "system_metrics": {
            model_ids[0]: {"graded_ndcg@10": 0.7},
            model_ids[1]: {"graded_ndcg@10": 0.6},
        },
        "system_metric_query_counts": {
            model_ids[0]: {"graded_ndcg@10": 3},
            model_ids[1]: {"graded_ndcg@10": 3},
        },
        "system_metric_excluded_query_counts": {
            model_ids[0]: {"graded_ndcg@10": 0},
            model_ids[1]: {"graded_ndcg@10": 0},
        },
        "p95_inference_latency_ms": {model_ids[0]: 1.0, model_ids[1]: 1.1},
        "strongest_baseline_id": model_ids[0],
        "strongest_baseline_value": 0.7,
        "validation_query_count": 3,
        "excluded_query_count": 0,
        "rankings": {model_id: f"rankings/{model_id}.jsonl" for model_id in model_ids},
        "resumed_from_run_id": None,
    }
    baseline_path = tmp_path / "baseline-summary.json"
    baseline_path.write_text(json.dumps(baseline, sort_keys=True) + "\n", encoding="utf-8")
    curated_path = write_curated_queries(
        tmp_path / "curated-queries.json",
        [_query(10), _query(20), _query(40)],
    )
    command = {
        "schema_version": "1.0.0",
        "run_id": "baseline-run-deterministic",
        "command": "baseline-run",
        "status": "succeeded",
        "config_path": str(CONFIG_PATH),
        "started_at": "2026-09-02T00:00:00Z",
        "ended_at": ENDED_AT,
        "duration_seconds": 60.0,
        "git_sha": GIT_SHA,
        "repository_dirty": False,
        "runtime": {"python": "3.11", "platform": "fixture"},
        "artifact_paths": {
            "baseline_summary": str(baseline_path),
            "curated_queries": str(curated_path),
        },
        "artifact_hashes": {
            "baseline_summary": f"sha256:{sha256_file(baseline_path)}",
            "curated_queries": f"sha256:{sha256_file(curated_path)}",
        },
        "result": {
            "baseline_summary": str(baseline_path),
            "curated_queries": str(curated_path),
        },
        "failure": None,
    }
    command_path = tmp_path / "command-summary.json"
    command_path.write_text(json.dumps(command, sort_keys=True) + "\n", encoding="utf-8")
    dataset_pointer = tmp_path / "dataset-pointer.json"
    dataset_pointer.write_text("{}\n", encoding="utf-8")
    return command_path, curated_path, dataset_pointer


def _bundle_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_baseline_bootstrap_is_byte_identical_for_identical_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command_path, curated_path, dataset_pointer = _inputs(tmp_path)
    manifest = SimpleNamespace(
        processed_checksum=DATASET_HASH,
        split_manifest_hash=SPLIT_HASH,
        dataset_name="fixture",
        dataset_version="v1",
    )
    monkeypatch.setattr("search_rank.cli.load_dataset_manifest", lambda _: (manifest, Path("x")))
    monkeypatch.setenv("SEARCH_RANK_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("SEARCH_RANK_LATEST_ROOT", str(tmp_path / "latest"))

    outputs = (tmp_path / "release-one", tmp_path / "release-two")
    for output in outputs:
        bootstrap_baseline_release(
            baseline_summary=command_path,
            baseline_config=CONFIG_PATH,
            dataset_manifest=dataset_pointer,
            curated_queries=curated_path,
            output_dir=output,
            image_digest=IMAGE_DIGEST,
            git_sha=GIT_SHA,
            hardware_class="github-hosted-ubuntu-x86_64",
            region="us-east-1",
        )

    assert _bundle_hashes(outputs[0]) == _bundle_hashes(outputs[1])
    manifest_payload = json.loads((outputs[0] / "release-manifest.json").read_text())
    selected = next(
        model for model in manifest_payload["models"] if model["model_id"] == "bm25-enriched-v1"
    )
    assert selected["public_summary"]["promoted_at"] == "2026-09-02T00:01:00Z"
    public_evidence = json.loads((outputs[0] / "public-evidence.json").read_text())
    assert any(
        "image_digest binds the reviewed evaluation container" in limitation
        for limitation in public_evidence["run"]["limitations"]
    )
