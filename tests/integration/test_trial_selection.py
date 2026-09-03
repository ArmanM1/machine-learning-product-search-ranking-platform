from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tarfile
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from search_rank.artifacts.checksums import sha256_directory, sha256_file
from search_rank.schemas import TrialSelection
from search_rank.training.configuration import load_frozen_experiment

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "project_trial_selection", ROOT / "scripts" / "trial_selection.py"
)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery guard
    raise RuntimeError("unable to load scripts/trial_selection.py")
trial_selection = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = trial_selection
SPEC.loader.exec_module(trial_selection)
GIT_SHA = "a" * 40
IMAGE_DIGEST = "sha256:" + "b" * 64
DATASET_HASH = "sha256:420735e9bba265ae04797129003258974d8fed9e21272be318de7e49c97e24f6"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _trial_source(tmp_path: Path, role: str, ordinal: int) -> dict[str, Path | str]:
    config_relative = trial_selection.ROLE_PATHS[role]
    config_source = ROOT / config_relative
    config = load_frozen_experiment(config_source)
    run_id = f"product-search-ranking-prod-{role}-{ordinal}"
    model_id = f"candidate-{config.config_id}-{config.config_hash[7:19]}"
    model_key = f"runs/{run_id}/output/model.tar.gz"
    config_key = f"runs/{run_id}/config/experiment.yaml"
    manifest_key = f"runs/{run_id}/reports/run-manifest.json"
    release_inputs_key = f"runs/{run_id}/reports/candidate-release-inputs.json"
    source_root = tmp_path / f"archive-{role}"
    checkpoint = source_root / "candidate" / "best"
    checkpoint.mkdir(parents=True)
    (checkpoint / "model.safetensors").write_bytes(f"weights-{role}".encode())
    checkpoint_hash = "sha256:" + sha256_directory(checkpoint)
    frozen = source_root / "candidate" / "frozen-experiment.yaml"
    shutil.copy2(config_source, frozen)
    summary: dict[str, Any] = {
        "schema_version": "1.0.0",
        "run_id": f"container-{role}",
        "command": "train",
        "status": "succeeded",
        "config_path": "/opt/ml/input/config/experiment.yaml",
        "started_at": "2026-09-02T12:00:00Z",
        "ended_at": "2026-09-02T12:01:00Z",
        "duration_seconds": 60.0,
        "git_sha": "unavailable",
        "repository_dirty": False,
        "runtime": {"python": "3.11.9", "platform": "linux"},
        "artifact_paths": {},
        "artifact_hashes": {},
        "result": {
            "candidate_model_id": model_id,
            "checkpoint_checksum": checkpoint_hash,
            "config_hash": config.config_hash,
            "dataset_manifest_hash": config.dataset_manifest_hash,
            "best_validation_ndcg_at_10": 0.65 + ordinal / 100,
        },
        "failure": None,
    }
    _write_json(source_root / "summary.json", summary)
    archive = tmp_path / f"{role}.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source_root, arcname="model")
    archive_hash = sha256_file(archive)

    run_kind = "final" if role == "candidate_treatment" else "ablation"
    image_uri = (
        "123456789012.dkr.ecr.us-east-1.amazonaws.com/product-search-ranking-train@" + IMAGE_DIGEST
    )
    manifest = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "run_type": "training",
        "git_sha": GIT_SHA,
        "repository_dirty": False,
        "image_uri": image_uri,
        "image_digest": IMAGE_DIGEST,
        "config_hash": config.config_hash,
        "dataset_manifest_hash": DATASET_HASH,
        "cloud_project_alias": "product-search-ranking",
        "region": "us-east-1",
        "job_id": run_id,
        "hardware": "ml.g4dn.xlarge",
        "accelerator": "gpu",
        "device_type": "cuda",
        "cuda_available": True,
        "cuda_device_count": 1,
        "started_at": "2026-09-02T12:00:00Z",
        "ended_at": "2026-09-02T12:01:00Z",
        "duration_seconds": 60.0,
        "status": "succeeded",
        "failure_summary": None,
        "artifact_uris": {
            "model_artifact": f"s3://private-artifacts/{model_key}",
            "frozen_configuration": f"s3://private-artifacts/{config_key}",
        },
        "artifact_checksums": {
            "model_artifact": "sha256:" + archive_hash,
            "frozen_configuration": "sha256:" + sha256_file(config_source),
        },
        "estimated_cost_usd": 1.25,
        "actual_cost_usd": None,
    }
    manifest_path = tmp_path / "manifests" / f"{role}.json"
    _write_json(manifest_path, manifest)
    source = {
        "schema_version": "1.0.0",
        "artifact_type": "candidate_release_inputs",
        "candidate_run_id": run_id,
        "candidate_model_id": model_id,
        "candidate_artifact_s3_key": model_key,
        "candidate_artifact_sha256": archive_hash,
        "candidate_checkpoint_sha256": checkpoint_hash.removeprefix("sha256:"),
        "candidate_training_config_sha256": config.config_hash,
        "candidate_training_config_path": config_relative,
        "candidate_training_config_s3_key": config_key,
        "candidate_training_config_file_sha256": sha256_file(config_source),
        "dataset_manifest_hash": DATASET_HASH,
        "best_validation_ndcg_at_10": summary["result"]["best_validation_ndcg_at_10"],
        "training_run_kind": run_kind,
        "training_config_role": role,
        "git_sha": GIT_SHA,
        "repository_dirty": False,
        "training_image_uri": image_uri,
        "training_image_digest": IMAGE_DIGEST,
        "training_image_source_tag": "sha-" + GIT_SHA,
        "training_hardware": "ml.g4dn.xlarge",
        "training_accelerator": "gpu",
        "training_region": "us-east-1",
        "training_status": "succeeded",
        "training_billable_on_demand_upper_bound_usd": "0.012267",
        "training_run_manifest_s3_key": manifest_key,
        "training_run_manifest_sha256": "sha256:" + sha256_file(manifest_path),
        "source_identity_basis": "clean checkout and exact sha-commit ECR tag-to-digest binding",
    }
    release_inputs = tmp_path / "sources" / f"{role}.json"
    _write_json(release_inputs, source)
    return {
        "archive": archive,
        "manifest": manifest_path,
        "manifest_key": manifest_key,
        "release_inputs": release_inputs,
        "release_inputs_key": release_inputs_key,
    }


def _build_args(tmp_path: Path) -> Namespace:
    sources = {
        role: _trial_source(tmp_path, role, ordinal)
        for ordinal, role in enumerate(trial_selection.ROLES, start=1)
    }
    values: dict[str, object] = {
        "repository_root": str(ROOT),
        "git_sha": GIT_SHA,
        "output": str(tmp_path / "trial-selection.json"),
    }
    prefixes = {
        "candidate_treatment": "treatment",
        "random_negative_control": "random_negative",
        "title_only_control": "title_only",
    }
    for role, prefix in prefixes.items():
        values[f"{prefix}_release_inputs"] = str(sources[role]["release_inputs"])
        values[f"{prefix}_release_inputs_s3_key"] = sources[role]["release_inputs_key"]
        values[f"{prefix}_model_archive"] = str(sources[role]["archive"])
        values[f"{prefix}_run_manifest"] = str(sources[role]["manifest"])
        values[f"{prefix}_run_manifest_s3_key"] = sources[role]["manifest_key"]
    return Namespace(**values)


def test_three_trial_builder_binds_treatment_controls_and_zero_test_access(
    tmp_path: Path,
) -> None:
    args = _build_args(tmp_path)
    selection = trial_selection.build(args)

    assert selection.trial_count == 3
    assert selection.test_access_count == 0
    assert selection.heldout_accessed is False
    assert selection.selected_role == "candidate_treatment"
    assert {trial.role for trial in selection.trials} == set(trial_selection.ROLES)
    assert {trial.training_config_role for trial in selection.trials} == set(trial_selection.ROLES)
    assert selection.trials[0].training_git_sha == GIT_SHA

    verified = trial_selection.verify(
        Namespace(
            selection=args.output,
            git_sha=GIT_SHA,
            dataset_manifest_hash=DATASET_HASH,
            candidate_run_id=selection.selected_candidate_run_id,
            candidate_model_id=selection.selected_candidate_model_id,
            candidate_config_sha256=selection.selected_candidate_config_sha256,
            candidate_artifact_s3_key=selection.trials[0].candidate_artifact_s3_key,
            candidate_artifact_sha256=selection.trials[0].candidate_artifact_sha256,
            repository_root=str(ROOT),
            source_dir=str(tmp_path / "sources"),
            run_manifest_dir=str(tmp_path / "manifests"),
        )
    )
    assert verified == selection


def test_trial_selection_rejects_missing_control_and_metric_tamper(tmp_path: Path) -> None:
    selection = trial_selection.build(_build_args(tmp_path))
    payload = selection.model_dump(mode="json")
    payload["trials"] = payload["trials"][:-1]
    with pytest.raises(ValidationError, match=r"trial_count|mandatory role"):
        TrialSelection.model_validate(payload)

    payload = selection.model_dump(mode="json")
    payload["contrasts"][0]["treatment_minus_control"] = 0.9
    with pytest.raises(ValidationError, match="values do not match"):
        TrialSelection.model_validate(payload)


def test_release_workflow_verifies_selection_before_any_heldout_access() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    dispatch_example = json.loads(
        (ROOT / "docs" / "workflow-inputs" / "release.example.json").read_text(encoding="utf-8")
    )
    dispatch_validator = (ROOT / "scripts" / "validate_workflow_dispatch.py").read_text(
        encoding="utf-8"
    )
    freeze = (ROOT / ".github" / "workflows" / "freeze-trial-selection.yml").read_text(
        encoding="utf-8"
    )

    assert "trial_selection_s3_key" in dispatch_example
    assert "trial_selection_sha256" in dispatch_example
    assert '"trial_selection_s3_key": "TRIAL_SELECTION_S3_KEY"' in dispatch_validator
    assert '"trial_selection_sha256": "TRIAL_SELECTION_SHA256"' in dispatch_validator
    gate = release.index("Require the immutable treatment and both validation-only controls")
    first_counter = release.index("Capture the required rollback-safe baseline pointer")
    first_job = release.index("Run two separately counted clean held-out Processing jobs")
    assert gate < first_counter < first_job
    assert "scripts/trial_selection.py verify" in release[gate:first_counter]

    assert 'ALLOW_HELDOUT_EVAL: "0"' in freeze
    assert "scripts/trial_selection.py build" in freeze
    assert "scripts/trial_selection.py verify" in freeze
    assert "--if-none-match '*'" in freeze
