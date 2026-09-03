from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_release_artifacts import validate_frozen_baseline_evidence
from search_rank.artifacts.checksums import sha256_file
from search_rank.command_config import BaselineRunConfig
from search_rank.config import sha256_value, validate_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path("configs/experiments/baselines-v1.yaml")
GIT_SHA = "a" * 40
DATASET_HASH = "sha256:" + "b" * 64
BASELINE_IDS = ("bm25-v1", "pretrained-v1")


def _evidence(tmp_path: Path) -> tuple[Path, Path]:
    semantic_config_hash = f"sha256:{sha256_value(validate_config(CONFIG_PATH, BaselineRunConfig))}"
    rankings_dir = tmp_path / "rankings"
    rankings_dir.mkdir()
    ranking_paths = {
        "bm25-v1": rankings_dir / "00.jsonl",
        "pretrained-v1": rankings_dir / "01.jsonl",
    }
    for model_id, path in ranking_paths.items():
        path.write_text(json.dumps({"model_id": model_id}) + "\n", encoding="utf-8")
    curated_path = tmp_path / "curated-queries.json"
    curated_path.write_text('{"schema_version":"1.0.0","queries":[]}\n', encoding="utf-8")
    baseline = {
        "schema_version": "1.0.0",
        "config_hash": semantic_config_hash,
        "dataset_manifest_hash": DATASET_HASH,
        "dataset_name": "fixture",
        "dataset_version": "v1",
        "dataset_locale": "us",
        "split": "validation",
        "metrics": {"bm25-v1": 0.5, "pretrained-v1": 0.6},
        "system_metrics": {
            "bm25-v1": {"graded_ndcg@10": 0.5},
            "pretrained-v1": {"graded_ndcg@10": 0.6},
        },
        "system_metric_query_counts": {
            "bm25-v1": {"graded_ndcg@10": 10},
            "pretrained-v1": {"graded_ndcg@10": 10},
        },
        "system_metric_excluded_query_counts": {
            "bm25-v1": {"graded_ndcg@10": 0},
            "pretrained-v1": {"graded_ndcg@10": 0},
        },
        "p95_inference_latency_ms": {"bm25-v1": 1.0, "pretrained-v1": 2.0},
        "strongest_baseline_id": "pretrained-v1",
        "strongest_baseline_value": 0.6,
        "validation_query_count": 10,
        "excluded_query_count": 0,
        "rankings": {model_id: str(path) for model_id, path in ranking_paths.items()},
        "resumed_from_run_id": None,
    }
    baseline_path = tmp_path / "baseline-summary.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    command = {
        "schema_version": "1.0.0",
        "run_id": "baseline-run-fixture",
        "command": "baseline-run",
        "status": "succeeded",
        "config_path": f"/home/runner/work/project/project/{CONFIG_PATH.as_posix()}",
        "started_at": "2026-09-02T00:00:00Z",
        "ended_at": "2026-09-02T00:01:00Z",
        "duration_seconds": 60,
        "git_sha": GIT_SHA,
        "repository_dirty": False,
        "runtime": {"python": "3.11", "platform": "fixture"},
        "artifact_paths": {
            "ranking_00": str(ranking_paths["bm25-v1"]),
            "ranking_01": str(ranking_paths["pretrained-v1"]),
            "baseline_summary": str(baseline_path),
            "curated_queries": str(curated_path),
        },
        "artifact_hashes": {
            "ranking_00": f"sha256:{sha256_file(ranking_paths['bm25-v1'])}",
            "ranking_01": f"sha256:{sha256_file(ranking_paths['pretrained-v1'])}",
            "baseline_summary": f"sha256:{sha256_file(baseline_path)}",
            "curated_queries": f"sha256:{sha256_file(curated_path)}",
        },
        "result": {
            "config_hash": semantic_config_hash,
            "dataset_checksum": DATASET_HASH,
            "baseline_summary": str(baseline_path),
            "curated_queries": str(curated_path),
            "strongest_baseline_id": "pretrained-v1",
            "metrics": baseline["metrics"],
            "resumed_from_run_id": None,
        },
        "failure": None,
    }
    command_path = tmp_path / "command-summary.json"
    command_path.write_text(json.dumps(command), encoding="utf-8")
    return command_path, baseline_path


def _validate(command_path: Path, baseline_path: Path) -> str:
    return validate_frozen_baseline_evidence(
        command_summary_path=command_path,
        baseline_summary_path=baseline_path,
        baseline_config_path=CONFIG_PATH,
        baseline_config_file_sha256=sha256_file(CONFIG_PATH),
        baseline_summary_sha256=sha256_file(baseline_path),
        expected_git_sha=GIT_SHA,
        dataset_manifest_hash=DATASET_HASH,
        strongest_baseline_id="pretrained-v1",
        baseline_ids=BASELINE_IDS,
    )


def test_frozen_baseline_evidence_binds_clean_current_commit_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    command_path, baseline_path = _evidence(tmp_path)

    assert _validate(command_path, baseline_path) == (
        f"sha256:{sha256_value(validate_config(CONFIG_PATH, BaselineRunConfig))}"
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("git_sha", "c" * 40, "different Git revision"),
        ("git_sha", "unavailable", "different Git revision"),
        ("repository_dirty", True, "dirty repository"),
        ("config_path", "configs/experiments/other.yaml", "different config path"),
    ),
)
def test_frozen_baseline_evidence_rejects_unbound_command_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    monkeypatch.chdir(ROOT)
    command_path, baseline_path = _evidence(tmp_path)
    command = json.loads(command_path.read_text(encoding="utf-8"))
    command[field] = value
    command_path.write_text(json.dumps(command), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        _validate(command_path, baseline_path)


def test_frozen_baseline_evidence_rejects_unbound_semantic_config_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    command_path, baseline_path = _evidence(tmp_path)
    command = json.loads(command_path.read_text(encoding="utf-8"))
    command["result"]["config_hash"] = "sha256:" + "d" * 64
    command_path.write_text(json.dumps(command), encoding="utf-8")

    with pytest.raises(ValueError, match="config_hash"):
        _validate(command_path, baseline_path)


@pytest.mark.parametrize("artifact", ("ranking_00", "curated_queries"))
def test_frozen_baseline_evidence_rejects_incomplete_command_artifact_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: str
) -> None:
    monkeypatch.chdir(ROOT)
    command_path, baseline_path = _evidence(tmp_path)
    command = json.loads(command_path.read_text(encoding="utf-8"))
    command["artifact_paths"].pop(artifact)
    command["artifact_hashes"].pop(artifact)
    command_path.write_text(json.dumps(command), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact inventory is not exact"):
        _validate(command_path, baseline_path)


def test_frozen_baseline_evidence_rejects_extra_command_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    command_path, baseline_path = _evidence(tmp_path)
    command = json.loads(command_path.read_text(encoding="utf-8"))
    command["artifact_paths"]["unexpected"] = str(tmp_path / "unexpected.json")
    command["artifact_hashes"]["unexpected"] = "sha256:" + "e" * 64
    command_path.write_text(json.dumps(command), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact inventory is not exact"):
        _validate(command_path, baseline_path)


def test_frozen_baseline_evidence_rejects_mismatched_ranking_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    command_path, baseline_path = _evidence(tmp_path)
    command = json.loads(command_path.read_text(encoding="utf-8"))
    command["artifact_paths"]["ranking_00"] = command["artifact_paths"]["ranking_01"]
    command_path.write_text(json.dumps(command), encoding="utf-8")

    with pytest.raises(ValueError, match="ranking path differs from summary: ranking_00"):
        _validate(command_path, baseline_path)


def test_frozen_baseline_evidence_rejects_available_artifact_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    command_path, baseline_path = _evidence(tmp_path)
    command = json.loads(command_path.read_text(encoding="utf-8"))
    ranking_path = Path(command["artifact_paths"]["ranking_00"])
    ranking_path.write_text('{"model_id":"tampered"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="artifact checksum mismatch: ranking_00"):
        _validate(command_path, baseline_path)


@pytest.mark.parametrize("mutation", ("missing", "different"))
def test_frozen_baseline_evidence_rejects_unbound_retry_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    monkeypatch.chdir(ROOT)
    command_path, baseline_path = _evidence(tmp_path)
    command = json.loads(command_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        command["result"].pop("resumed_from_run_id")
    else:
        command["result"]["resumed_from_run_id"] = "baseline-run-failed-source"
    command_path.write_text(json.dumps(command), encoding="utf-8")

    with pytest.raises(ValueError, match="resumed_from_run_id"):
        _validate(command_path, baseline_path)


def test_baseline_workflow_attests_clean_commit_before_emitting_command_evidence() -> None:
    workflow = (ROOT / ".github/workflows/baseline.yml").read_text(encoding="utf-8")

    assert 'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"' in workflow
    assert 'test -z "$(git status --porcelain --untracked-files=all)"' in workflow
    assert 'SEARCH_RANK_GIT_SHA="${GITHUB_SHA}" \\' in workflow
    assert workflow.index('test -z "$(git status --porcelain --untracked-files=all)"') < (
        workflow.index('SEARCH_RANK_GIT_SHA="${GITHUB_SHA}" \\')
    )
