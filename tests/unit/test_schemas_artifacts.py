from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from search_rank.schemas import DatasetManifest, ModelArtifact, PromotionPointer, RunManifest
from search_rank.schemas.dataset import SplitManifestIdentity

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def dataset_manifest_values() -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "dataset_name": "Amazon Shopping Queries ESCI",
        "dataset_version": "small-v1",
        "source_url": "https://example.invalid/source",
        "source_revision": "abc1234",
        "license_url": "https://example.invalid/license",
        "license_notice_hash": SHA_A,
        "task": "query-product reranking",
        "locale": "us",
        "raw_checksums": {"examples.parquet": SHA_A, "products.parquet": SHA_B},
        "preprocessing_version": "normalize-v1",
        "split_strategy": "official-test_stable-hash-validation-v1",
        "split_salt_hash": SHA_B,
        "split_counts": {
            "train": {"query_count": 10, "row_count": 100, "product_count": 90},
            "validation": {"query_count": 2, "row_count": 20, "product_count": 19},
            "test": {"query_count": 3, "row_count": 30, "product_count": 28},
        },
        "split_query_id_hashes": {"train": SHA_A, "validation": SHA_B, "test": SHA_A},
        "row_count": 150,
        "query_count": 15,
        "product_count": 137,
        "label_distribution": {"Exact": 30, "Substitute": 40, "Complement": 20, "Irrelevant": 60},
        "missingness": {"product_brand": 8},
        "dropped_rows": {"duplicate_exact_row": 1},
        "processed_artifact_uri": "s3://private-bucket/data/manifest.parquet",
        "processed_checksum": SHA_A,
        "created_at": NOW,
    }
    values["split_manifest_hash"] = SplitManifestIdentity.model_validate(
        {
            "dataset_name": values["dataset_name"],
            "dataset_version": values["dataset_version"],
            "source_revision": values["source_revision"],
            "locale": values["locale"],
            "raw_checksums": values["raw_checksums"],
            "preprocessing_version": values["preprocessing_version"],
            "split_strategy": values["split_strategy"],
            "split_salt_hash": values["split_salt_hash"],
            "split_counts": values["split_counts"],
            "split_query_id_hashes": values["split_query_id_hashes"],
            "row_count": values["row_count"],
            "query_count": values["query_count"],
        }
    ).checksum()
    return values


def test_dataset_manifest_round_trip_and_required_field_validation() -> None:
    manifest = DatasetManifest.model_validate(dataset_manifest_values())
    assert DatasetManifest.model_validate_json(manifest.model_dump_json()) == manifest
    missing = dataset_manifest_values()
    del missing["processed_checksum"]
    with pytest.raises(ValidationError, match="processed_checksum"):
        DatasetManifest.model_validate(missing)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("row_count", 149, "row_count must equal"),
        ("query_count", 14, "query_count must equal"),
        ("product_count", 151, "product_count cannot exceed"),
    ],
)
def test_dataset_manifest_aggregate_counts_are_exact(field: str, value: int, message: str) -> None:
    values = dataset_manifest_values()
    values[field] = value
    with pytest.raises(ValidationError, match=message):
        DatasetManifest.model_validate(values)


def test_dataset_manifest_rejects_split_identity_tamper() -> None:
    values = dataset_manifest_values()
    split_counts = values["split_counts"]
    assert isinstance(split_counts, dict)
    train = split_counts["train"]
    assert isinstance(train, dict)
    train["product_count"] = 89
    with pytest.raises(ValidationError, match="split_manifest_hash"):
        DatasetManifest.model_validate(values)


def test_artifact_contracts_reject_unknown_fields_and_unprefixed_hashes() -> None:
    values = dataset_manifest_values()
    values["typo_field"] = 1
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DatasetManifest.model_validate(values)
    values = dataset_manifest_values()
    values["processed_checksum"] = "a" * 64
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        DatasetManifest.model_validate(values)


def test_timestamps_must_be_timezone_aware_and_serialize_as_utc() -> None:
    values = dataset_manifest_values()
    values["created_at"] = datetime(2026, 9, 2, 12, 0)
    with pytest.raises(ValidationError, match="UTC offset"):
        DatasetManifest.model_validate(values)

    values["created_at"] = "2026-09-02T06:00:00-06:00"
    manifest = DatasetManifest.model_validate(values)
    assert manifest.created_at == NOW
    assert manifest.model_dump(mode="json")["created_at"].endswith("Z")


def test_run_manifest_enforces_terminal_lifecycle_and_artifact_checksums() -> None:
    values = {
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "run_type": "evaluation",
        "git_sha": "abcdef1",
        "repository_dirty": False,
        "image_uri": "local://image",
        "image_digest": SHA_A,
        "config_hash": SHA_A,
        "dataset_manifest_hash": SHA_B,
        "cloud_project_alias": "portfolio-search",
        "region": "us-east-1",
        "job_id": "local-job-1",
        "hardware": "local-cpu",
        "accelerator": None,
        "started_at": "2026-09-02T12:00:00Z",
        "ended_at": "2026-09-02T12:01:00Z",
        "duration_seconds": 60.0,
        "status": "succeeded",
        "failure_summary": None,
        "artifact_uris": {"report": "local://report.json"},
        "artifact_checksums": {"report": SHA_A},
        "estimated_cost_usd": 0,
        "actual_cost_usd": 0,
    }
    assert RunManifest.model_validate(values).status == "succeeded"
    values["artifact_checksums"] = {}
    with pytest.raises(ValidationError, match="same-key"):
        RunManifest.model_validate(values)


def model_artifact_values() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "model_id": "candidate-v1",
        "run_id": "run-1",
        "base_model_id": "base",
        "base_model_revision": "rev",
        "tokenizer_revision": "rev",
        "checkpoint_uri": "candidate/best",
        "artifact_checksum": SHA_A,
        "artifact_size_bytes": 123,
        "config_id": "candidate-v1",
        "config_hash": SHA_B,
        "dataset_manifest_hash": SHA_A,
        "input_contract_version": "enriched_v1",
        "label_mapping_version": "project_graded_v1",
        "sampling_strategy": "mixed_hard_random_v1",
        "hard_example_sources": ["bm25", "pretrained_cross_encoder"],
        "promoted": False,
        "promotion_reason": "pending held-out evaluation",
        "evaluation_report_id": "not_evaluated",
        "sample_statistics": {
            "row_count": 2,
            "sampling_source_counts": {"hard": 1, "random": 1},
            "label_counts": {"Exact": 1, "Irrelevant": 1},
        },
        "training_result": {
            "best_checkpoint": "candidate/best",
            "best_validation_ndcg_at_10": 0.7,
            "epochs_completed": 1,
            "optimizer_steps": 2,
            "duration_seconds": 3.0,
            "changed_parameter_count": 1,
            "curves_path": "candidate/curves.json",
            "fresh_load_verified": True,
            "warmup_steps": 1,
            "planned_optimizer_steps": 2,
            "device_type": "cuda",
            "cuda_available": True,
            "cuda_device_count": 1,
            "accelerator_type": "gpu",
        },
        "created_at": NOW,
    }


def test_model_artifact_requires_preregistered_mapping() -> None:
    values = model_artifact_values()
    values["label_mapping_version"] = "changed-after-test"
    with pytest.raises(ValidationError, match="project_graded_v1"):
        ModelArtifact.model_validate(values)


@pytest.mark.parametrize(
    ("promoted", "reason"),
    [
        (True, "held-out release gates passed"),
        (False, "held-out release gates failed; prior baseline retained"),
    ],
)
def test_final_model_artifact_binds_source_run_manifest_and_evaluation(
    promoted: bool, reason: str
) -> None:
    source = ModelArtifact.model_validate(model_artifact_values())
    values = source.model_dump(mode="json")
    values.update(
        {
            "git_sha": "d" * 40,
            "image_digest": SHA_B,
            "promoted": promoted,
            "promotion_reason": reason,
            "evaluation_report_id": "report-1",
            "source_model_artifact_sha256": SHA_A,
            "selected_training_run_manifest_sha256": SHA_B,
            "evaluation_report_sha256": SHA_A,
        }
    )
    artifact = ModelArtifact.model_validate(values)
    assert artifact.promoted is promoted
    assert artifact.source_model_artifact_sha256 == SHA_A

    values["evaluation_report_sha256"] = None
    with pytest.raises(ValidationError, match="require source, run-manifest, and report hashes"):
        ModelArtifact.model_validate(values)


def test_unevaluated_model_artifact_cannot_claim_final_release_binding() -> None:
    values = model_artifact_values()
    values["source_model_artifact_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="cannot claim final release bindings"):
        ModelArtifact.model_validate(values)


def test_checked_in_json_schemas_are_valid_documents_with_required_fields() -> None:
    schema_dir = Path("schemas/json")
    expected = {
        "dataset_manifest.schema.json": "processed_checksum",
        "experiment_config.schema.json": "deterministic_mode",
        "run_manifest.schema.json": "artifact_checksums",
        "model_artifact.schema.json": "promotion_reason",
        "evaluation_report.schema.json": "release_gate_results",
        "promotion_pointer.schema.json": "release_decision",
        "trial_selection.schema.json": "test_access_count",
        "public_training_provenance.schema.json": "trial_selection_sha256",
        "public_evaluation_provenance.schema.json": "clean_execution_count",
    }
    for filename, required_field in expected.items():
        schema = json.loads((schema_dir / filename).read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert required_field in schema["required"]
        assert schema["additionalProperties"] is False
    model_schema = json.loads((schema_dir / "model_artifact.schema.json").read_text())
    assert "evaluation_report_sha256" in model_schema["properties"]


def test_checked_in_json_schemas_match_pydantic_contracts() -> None:
    specifications = {
        "dataset_manifest.schema.json": ("search_rank.schemas.dataset", "DatasetManifest"),
        "experiment_config.schema.json": (
            "search_rank.schemas.experiment",
            "ExperimentConfig",
        ),
        "run_manifest.schema.json": ("search_rank.schemas.run", "RunManifest"),
        "model_artifact.schema.json": ("search_rank.schemas.model", "ModelArtifact"),
        "evaluation_report.schema.json": (
            "search_rank.schemas.evaluation",
            "EvaluationReport",
        ),
        "promotion_pointer.schema.json": (
            "search_rank.schemas.release",
            "PromotionPointer",
        ),
        "trial_selection.schema.json": (
            "search_rank.schemas.trial",
            "TrialSelection",
        ),
        "public_training_provenance.schema.json": (
            "search_rank.schemas.api",
            "PublicTrainingProvenance",
        ),
        "public_evaluation_provenance.schema.json": (
            "search_rank.schemas.api",
            "PublicEvaluationProvenance",
        ),
        "rank_request.schema.json": ("search_rank.schemas.api", "RankRequest"),
        "ranked_product.schema.json": ("search_rank.schemas.api", "RankedProduct"),
        "rank_response.schema.json": ("search_rank.schemas.api", "RankResponse"),
        "comparison_response.schema.json": (
            "search_rank.schemas.api",
            "ComparisonResponse",
        ),
        "curated_query_summary.schema.json": (
            "search_rank.schemas.api",
            "CuratedQuerySummary",
        ),
        "model_summary.schema.json": ("search_rank.schemas.api", "ModelSummary"),
        "public_run_summary.schema.json": (
            "search_rank.schemas.api",
            "PublicRunSummary",
        ),
        "public_evidence_envelope.schema.json": (
            "search_rank.schemas.api",
            "PublicEvidenceEnvelope",
        ),
        "api_error.schema.json": ("search_rank.schemas.api", "ApiError"),
        "health_response.schema.json": ("search_rank.schemas.api", "HealthResponse"),
        "ready_response.schema.json": ("search_rank.schemas.api", "ReadyResponse"),
    }
    for filename, (module_name, model_name) in specifications.items():
        document = json.loads((Path("schemas/json") / filename).read_text(encoding="utf-8"))
        document.pop("$schema")
        document.pop("$id")
        model = getattr(importlib.import_module(module_name), model_name)
        assert document == model.model_json_schema(), filename


def test_promotion_pointer_publishes_failed_evidence_without_promoting_candidate() -> None:
    pointer = PromotionPointer.model_validate(
        {
            "schema_version": "1.0.0",
            "release_id": "report-heldout-1",
            "model_id": "pretrained-baseline-v1",
            "bundle_s3_key": "promoted/releases/report-heldout-1/",
            "evaluation_report_id": "report-heldout-1",
            "git_sha": "abcdef0123456789",
            "evidence_mode": "verified",
            "release_decision": "retain_baseline",
            "gate_passed": False,
            "evaluated_candidate_model_id": "candidate-v1",
            "previous": {
                "release_id": "baseline-bootstrap-1",
                "model_id": "pretrained-baseline-v1",
                "pointer_version_id": "version-1",
            },
        }
    )
    assert pointer.model_id == pointer.previous.model_id  # type: ignore[union-attr]
    assert pointer.model_id != pointer.evaluated_candidate_model_id


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_id", "candidate-v1", "cannot activate the evaluated candidate"),
        ("bundle_s3_key", "promoted/pretrained-baseline-v1/", "immutable canonical key"),
    ],
)
def test_promotion_pointer_rejects_false_or_mutable_failed_publication(
    field: str, value: object, message: str
) -> None:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "release_id": "report-heldout-1",
        "model_id": "pretrained-baseline-v1",
        "bundle_s3_key": "promoted/releases/report-heldout-1/",
        "evaluation_report_id": "report-heldout-1",
        "git_sha": "abcdef0123456789",
        "evidence_mode": "verified",
        "release_decision": "retain_baseline",
        "gate_passed": False,
        "evaluated_candidate_model_id": "candidate-v1",
        "previous": {
            "release_id": "baseline-bootstrap-1",
            "model_id": "pretrained-baseline-v1",
            "pointer_version_id": "version-1",
        },
    }
    payload[field] = value
    with pytest.raises(ValidationError, match=message):
        PromotionPointer.model_validate(payload)
