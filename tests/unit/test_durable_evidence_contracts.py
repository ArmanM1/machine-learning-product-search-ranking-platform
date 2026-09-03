from __future__ import annotations

import importlib
import json
import math
import statistics
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from search_rank.schemas.evidence import BundleChecksums, ReleaseManifest
from search_rank.schemas.workflow import (
    AutomaticDeploymentRollback,
    BenchmarkCostPreflight,
    CandidateReleaseInputs,
    DeploymentEvidence,
    ManualRollbackEvidence,
    PerformanceReport,
    PerformanceValidation,
    SageMakerManagedSpotQuotaPreflight,
)

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
GIT_SHA = "d" * 40
FINANCIAL_SNAPSHOT = {
    "schema_version": "1.0.0",
    "observed_at": "2026-09-02T12:00:00Z",
    "validated_at": "2026-09-02T12:00:00Z",
    "maximum_age_seconds": 21_600,
    "age_seconds_at_validation": 0,
    "source": "aws_billing_and_cost_management_console",
    "authorization_workflow": "train",
    "authorization_operation_id": "sha256:" + "f" * 64,
    "authorization_input_sha256": "sha256:" + "e" * 64,
    "authorization_commit_sha": "d" * 40,
    "authorization_reservation_sha256": "sha256:" + "c" * 64,
    "receipt_binding_algorithm": "hmac-sha256-v2",
    "receipt_sha256": SHA_A,
    "campaign_spend_to_date_redacted": True,
    "remaining_applicable_credit_redacted": True,
}


def test_sagemaker_managed_spot_quota_preflight_binds_exact_live_quota() -> None:
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "sagemaker_managed_spot_quota_preflight",
        "checked_at": "2026-09-02T12:00:00Z",
        "region": "us-east-1",
        "service_code": "sagemaker",
        "instance_type": "ml.g4dn.xlarge",
        "quota_code": "L-944F78BB",
        "quota_name": "ml.g4dn.xlarge for spot training job usage",
        "applied_value": 1.0,
        "required_value": 1,
        "quota_guard_passed": True,
    }
    assert SageMakerManagedSpotQuotaPreflight.model_validate(payload).applied_value == 1

    wrong_mapping = {**payload, "quota_code": "L-4CEE6BA6"}
    with pytest.raises(ValidationError, match="does not match"):
        SageMakerManagedSpotQuotaPreflight.model_validate(wrong_mapping)

    no_capacity = {**payload, "applied_value": 0}
    with pytest.raises(ValidationError):
        SageMakerManagedSpotQuotaPreflight.model_validate(no_capacity)


def test_benchmark_cost_and_validation_receipts_are_run_and_report_bound() -> None:
    cost = {
        "schema_version": "1.0.0",
        "artifact_type": "benchmark_cost_preflight",
        "status": "passed",
        "checked_at": "2026-09-02T12:00:00Z",
        "benchmark_run_id": "github-123-attempt-1",
        "release_id": "release-1",
        "model_id": "candidate-v1",
        "region": "us-east-1",
        "public_origin": "https://example.cloudfront.net",
        "maximum_out_of_pocket_usd": "0",
        "campaign_envelope_usd": "40",
        "required_credit_reserve_usd": "40",
        "conservative_benchmark_allowance_usd": "0.50",
        "heldout_access_enabled": False,
        "sensitive_balance_values_recorded": False,
        "financial_snapshot": FINANCIAL_SNAPSHOT,
    }
    assert BenchmarkCostPreflight.model_validate(cost).release_id == "release-1"
    with pytest.raises(ValidationError):
        BenchmarkCostPreflight.model_validate({**cost, "benchmark_run_id": "latest"})

    validation = {
        "schema_version": "1.0.0",
        "status": "passed",
        "validated_at": "2026-09-02T12:10:01Z",
        "benchmark_run_id": "github-123-attempt-1",
        "release_id": "release-1",
        "model_id": "candidate-v1",
        "performance_report_sha256": SHA_A,
        "evidence_file_count": 5,
        "condition_count": 9,
        "controlled_cold_start_sample_count": 1,
        "warmup_request_count": 90,
        "measured_request_count": 1800,
        "success_thresholds_enforced": True,
        "minimum_warmup_condition_success_count": 10,
        "primary_latency_condition_success_count": 200,
        "minimum_secondary_condition_success_count": 200,
        "immutability_required": True,
    }
    assert PerformanceValidation.model_validate(validation).performance_report_sha256 == SHA_A
    with pytest.raises(ValidationError):
        PerformanceValidation.model_validate({**validation, "evidence_file_count": 4})


def _model(
    model_id: str,
    kind: str,
    checksum: str,
    *,
    promoted: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_id": model_id,
        "kind": kind,
        "text_template": "enriched_v1",
        "artifact_checksum": checksum,
        "public_summary": {
            "model_id": model_id,
            "display_name": model_id,
            "kind": kind,
            "base_model_id": None if kind == "bm25" else "base/model",
            "artifact_checksum": checksum,
            "evaluation_report_id": "validation-run-1",
            "promoted_at": "2026-09-02T12:00:00Z" if promoted else None,
            "limitations_url": "/methodology#limitations",
        },
    }
    if kind != "bm25":
        payload.update({"checkpoint": "models/pretrained", "batch_size": 32})
    return payload


def test_release_manifest_and_checksum_inventory_fail_closed() -> None:
    manifest = ReleaseManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "release_id": "baseline-run-1",
            "promoted_model_id": "bm25-enriched",
            "dataset_manifest_hash": SHA_A,
            "split_manifest_hash": SHA_C,
            "evaluation_report_id": "validation-run-1",
            "git_sha": GIT_SHA,
            "evidence_mode": "validation_only",
            "artifact_checksums": {
                "baseline-summary.json": SHA_A,
                "curated-queries.json": SHA_B,
                "public-evidence.json": SHA_C,
                "LICENSE": SHA_A,
                "NOTICE": SHA_B,
            },
            "models": [
                _model("bm25-enriched", "bm25", SHA_A, promoted=True),
                _model("pretrained-baseline", "pretrained", SHA_B, promoted=False),
            ],
        }
    )
    assert manifest.promoted_model_id == "bm25-enriched"

    invalid = manifest.model_dump(mode="json")
    invalid["artifact_checksums"].pop("NOTICE")
    with pytest.raises(ValidationError, match="inventory is not exact"):
        ReleaseManifest.model_validate(invalid)

    assert BundleChecksums.model_validate(
        {"schema_version": "1.0.0", "files": {"models/model.bin": SHA_A}}
    ).files
    with pytest.raises(ValidationError, match="parent segments"):
        BundleChecksums.model_validate(
            {"schema_version": "1.0.0", "files": {"models/../secret": SHA_A}}
        )


def candidate_release_inputs() -> dict[str, Any]:
    run_id = "product-search-ranking-prod-final-123"
    return {
        "schema_version": "1.0.0",
        "artifact_type": "candidate_release_inputs",
        "candidate_run_id": run_id,
        "candidate_model_id": "candidate-v1-abcdef",
        "candidate_artifact_s3_key": f"runs/{run_id}/output/model.tar.gz",
        "candidate_artifact_sha256": "a" * 64,
        "candidate_checkpoint_sha256": "b" * 64,
        "candidate_training_config_sha256": SHA_C,
        "candidate_training_config_path": "configs/experiments/candidate-v1.yaml",
        "candidate_training_config_s3_key": f"runs/{run_id}/config/experiment.yaml",
        "candidate_training_config_file_sha256": "d" * 64,
        "dataset_manifest_hash": SHA_A,
        "best_validation_ndcg_at_10": 0.7,
        "training_run_kind": "final",
        "training_config_role": "candidate_treatment",
        "git_sha": GIT_SHA,
        "repository_dirty": False,
        "training_image_uri": (
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/product-search-ranking-train@" + SHA_B
        ),
        "training_image_digest": SHA_B,
        "training_image_source_tag": "sha-" + GIT_SHA,
        "training_hardware": "ml.g4dn.xlarge",
        "training_accelerator": "gpu",
        "training_region": "us-east-1",
        "training_status": "succeeded",
        "training_billable_on_demand_upper_bound_usd": "0.25",
        "training_run_manifest_s3_key": f"runs/{run_id}/reports/run-manifest.json",
        "training_run_manifest_sha256": SHA_A,
        "source_identity_basis": ("clean checkout and exact sha-commit ECR tag-to-digest binding"),
    }


def test_candidate_release_inputs_bind_role_image_and_run_prefix() -> None:
    artifact = CandidateReleaseInputs.model_validate(candidate_release_inputs())
    assert artifact.training_config_role == "candidate_treatment"

    invalid = candidate_release_inputs()
    invalid["candidate_training_config_s3_key"] = "runs/other/config/experiment.yaml"
    with pytest.raises(ValidationError, match="outside the candidate run"):
        CandidateReleaseInputs.model_validate(invalid)


def cold_start() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "status": "measured",
        "measurement_class": "controlled_on_demand_lambda_cold_start",
        "controlled_cold_start": True,
        "measured_at": "2026-09-02T12:01:00Z",
        "identifiers": {
            "release_id": "release-1",
            "model_id": "candidate-v1",
            "dataset_manifest_hash": SHA_A,
            "model_artifact_checksum": SHA_B,
            "function_name": "product-search-ranking-prod",
            "alias": "candidate",
            "function_version": "2",
            "region": "us-east-1",
        },
        "control_proof": {
            "newly_published_after_apply_started": True,
            "candidate_version_changed": True,
            "previous_candidate_version": "1",
            "new_version_prior_cloudwatch_event_count": 0,
            "on_demand_execution": True,
            "reserved_concurrency": 2,
            "provisioned_concurrency": 0,
        },
        "first_request": {
            "request_id": "request-1",
            "route": "/api/v1/rank",
            "http_status": 200,
            "candidate_count": 40,
            "end_to_end_latency_ms": 1000.0,
            "model_latency_ms": 100.0,
        },
        "lambda_report": {
            "init_duration_ms": 800.0,
            "invocation_duration_ms": 200.0,
            "billed_duration_ms": 1000.0,
            "configured_memory_mb": 4096,
            "max_memory_used_mb": 1000.0,
        },
        "structured_startup": {
            "startup_succeeded": True,
            "model_load_duration_ms": 700.0,
        },
        "structured_request": {"process_peak_memory_mb": 900.0},
        "sample_count": 1,
        "excluded_from_warm_samples": True,
        "limitations": ["One controlled observation is not a distribution."],
    }


def candidate_gate() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "status": "passed",
        "scope": "candidate_alias_primary_release_gate",
        "valid_request_count": 200,
        "failure_count": 0,
        "error_rate": 0.0,
        "error_rate_target": "less_than_0.01",
        "warmup_request_count": 10,
        "candidate_count": 40,
        "concurrency": 1,
        "end_to_end_latency_ms": {"p50": 100.0, "p95": 200.0, "p99": 250.0},
        "model_latency_ms": {"p50": 20.0, "p95": 40.0, "p99": 50.0},
        "lambda_memory_mb": 4096,
        "architecture": "x86_64",
        "region": "us-east-1",
        "reserved_concurrency": 2,
        "provisioned_concurrency": 0,
        "measurement_phase": "warm_after_ten_explicit_warmups",
        "controlled_cold_start_evidence_file": "candidate-cold-start.json",
        "controlled_cold_sample_included": False,
        "limitations": ["Concurrency one only."],
    }


def smoke() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "status": "passed",
        "scope": "bounded_release_smoke",
        "base_url_origin": "https://example.cloudfront.net",
        "model_id": "candidate-v1",
        "evaluated_candidate_model_id": "candidate-v1",
        "query_id": "q1",
        "candidate_count": 40,
        "rank_requests": 3,
        "comparison_checked": True,
        "request_count": 8,
        "error_count": 0,
        "latency_ms": {"minimum": 10.0, "median": 20.0, "maximum": 30.0, "rank_median": 25.0},
        "production_error_rate_claim_eligible": False,
        "note": "Bounded smoke only.",
    }


def deployment_evidence() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "deployment_evidence",
        "release_id": "release-1",
        "model_id": "candidate-v1",
        "code_commit": GIT_SHA,
        "serving_image_digest": SHA_C,
        "previous_lambda_version": "1",
        "production_lambda_version": "2",
        "promoted_pointer_version_id": "version-id-1",
        "smoke_tests_passed": True,
        "controlled_cold_start": cold_start(),
        "candidate_api_gate": candidate_gate(),
        "production_api_smoke": smoke(),
        "browser_smoke": {"desktop": True, "mobile": True, "keyboard": True},
    }


def test_deployment_evidence_binds_cold_and_production_versions() -> None:
    evidence = DeploymentEvidence.model_validate(deployment_evidence())
    assert evidence.controlled_cold_start.excluded_from_warm_samples is True

    invalid = deployment_evidence()
    invalid["production_lambda_version"] = "3"
    with pytest.raises(ValidationError, match="cold-start version"):
        DeploymentEvidence.model_validate(invalid)


def test_deployment_rollback_contracts_reject_untyped_or_unverified_results() -> None:
    automatic = {
        "schema_version": "1.0.0",
        "artifact_type": "automatic_deployment_rollback",
        "status": "automatically_rolled_back",
        "rollback_trigger": "post_activation_failure",
        "failed_release_id": "release-1",
        "restored_lambda_version": "2",
        "restored_pointer_version_id": "pointer-version-2",
        "service_disabled": False,
    }
    assert AutomaticDeploymentRollback.model_validate(automatic).service_disabled is False
    with pytest.raises(ValidationError):
        AutomaticDeploymentRollback.model_validate({**automatic, "rollback_trigger": "unknown"})

    manual = {
        "schema_version": "1.0.0",
        "artifact_type": "manual_rollback_evidence",
        "restored_release_id": "release-0",
        "restored_model_id": "baseline-v1",
        "from_lambda_version": "3",
        "to_lambda_version": "2",
        "restored_pointer_version_id": "pointer-version-3",
        "workflow_commit": GIT_SHA,
        "smoke_test_passed": True,
    }
    assert ManualRollbackEvidence.model_validate(manual).smoke_test_passed is True
    with pytest.raises(ValidationError):
        ManualRollbackEvidence.model_validate({**manual, "smoke_test_passed": False})


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def sample_summary(count: int, *, success_count: int | None = None) -> dict[str, Any]:
    success_count = count if success_count is None else success_count
    samples: list[dict[str, Any]] = [
        (
            {
                "ordinal": ordinal,
                "ok": True,
                "http_status": 200,
                "throttled": False,
                "end_to_end_ms": float(ordinal),
                "model_ms": float(ordinal) / 2,
            }
            if ordinal <= success_count
            else {
                "ordinal": ordinal,
                "ok": False,
                "http_status": 503,
                "throttled": False,
                "end_to_end_ms": float(ordinal),
                "model_ms": None,
                "error_category": "http_error",
            }
        )
        for ordinal in range(1, count + 1)
    ]

    def summary(values: list[float]) -> dict[str, float]:
        return {
            "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
            "mean": statistics.fmean(values),
            "minimum": min(values),
            "maximum": max(values),
        }

    successful = [sample for sample in samples if sample["ok"]]
    return {
        "sample_count": count,
        "success_count": success_count,
        "error_count": count - success_count,
        "throttle_count": 0,
        "http_status_and_transport_counts": {
            **({"200": success_count} if success_count else {}),
            **({"503": count - success_count} if success_count < count else {}),
        },
        "end_to_end_latency_ms": (
            summary([sample["end_to_end_ms"] for sample in successful]) if successful else None
        ),
        "model_latency_ms": (
            summary([sample["model_ms"] for sample in successful]) if successful else None
        ),
        "samples": samples,
    }


def performance_report() -> dict[str, Any]:
    conditions = [
        {
            "candidate_count": count,
            "query_id": f"q-{count}",
            "offered_concurrency": concurrency,
            "warmup": sample_summary(10),
            "measured": sample_summary(200),
        }
        for count in (10, 20, 40)
        for concurrency in (1, 4, 8)
    ]
    return {
        "schema_version": "1.0.0",
        "artifact_type": "serving_performance_report",
        "status": "completed",
        "scope": "manual_post_deployment_lambda_performance_protocol",
        "started_at": "2026-09-02T12:00:00Z",
        "completed_at": "2026-09-02T12:10:00Z",
        "identifiers": {
            "benchmark_run_id": "github-123-attempt-1",
            "release_id": "release-1",
            "public_run_id": "run-1",
            "model_id": "candidate-v1",
            "evidence_mode": "verified",
            "release_git_sha": GIT_SHA,
            "benchmark_harness_git_sha": GIT_SHA,
            "dataset_manifest_hash": SHA_A,
            "model_artifact_checksum": SHA_B,
            "region": "us-east-1",
            "public_origin": "https://example.cloudfront.net",
        },
        "release_binding": {
            "promotion_pointer_version_id": "pointer-version",
            "promotion_pointer_etag": '"etag-1"',
            "bundle_s3_key": "promoted/releases/release-1/",
            "release_manifest_sha256": SHA_A,
            "public_evidence_sha256": SHA_B,
            "bundle_checksums_sha256": SHA_C,
            "deployment_evidence_version_id": "deployment-version",
            "deployment_evidence_etag": '"etag-2"',
            "deployment_evidence_sha256": SHA_A,
        },
        "lambda_configuration": {
            "schema_version": "1.0.0",
            "checked_at": "2026-09-02T12:00:00Z",
            "benchmark_run_id": "github-123-attempt-1",
            "release_id": "release-1",
            "model_id": "candidate-v1",
            "function_name": "product-search-ranking-prod",
            "alias": "production",
            "function_version": "2",
            "memory_mb": 4096,
            "architecture": "x86_64",
            "reserved_concurrency": 2,
            "provisioned_concurrency": 0,
            "provisioned_concurrency_verification": (
                "live GetProvisionedConcurrencyConfig returned a not-found response"
            ),
            "region": "us-east-1",
        },
        "controlled_cold_start": cold_start(),
        "protocol": {
            "measurement_class": "warm_after_explicit_per_condition_warmups",
            "candidate_counts": [10, 20, 40],
            "offered_concurrency_levels": [1, 4, 8],
            "warmup_requests_per_condition": 10,
            "measured_requests_per_condition": 200,
            "condition_count": 9,
            "request_timeout_seconds": 20,
            "response_size_limit_bytes": 1_048_576,
            "minimum_warmup_successes_per_condition": 1,
            "primary_latency_candidate_count": 40,
            "primary_latency_offered_concurrency": 1,
            "primary_latency_minimum_successes": 199,
            "secondary_latency_minimum_successes": 20,
            "controlled_cold_sample_included": False,
            "pre_benchmark_observations_included": False,
        },
        "pre_benchmark_observations": {
            "cold_start_controlled": False,
            "health": {"http_status": 200, "end_to_end_ms": 10.0, "service_status": "ok"},
            "ready": {"http_status": 200, "end_to_end_ms": 10.0},
            "models": {"http_status": 200, "end_to_end_ms": 10.0},
            "queries": {"http_status": 200, "end_to_end_ms": 10.0},
            "run_evidence": {"http_status": 200, "end_to_end_ms": 10.0},
            "first_rank": sample_summary(1)["samples"][0],
            "excluded_from_warm_latency_percentiles": True,
        },
        "conditions": conditions,
        "totals": {
            "warmup_request_count": 90,
            "measured_request_count": 1800,
            "measured_success_count": 1800,
            "measured_error_count": 0,
            "measured_throttle_count": 0,
        },
        "interpretation": {
            "latency_claim": (
                "Warm public CloudFront end-to-end and model latency over successful responses "
                "after explicit warmups. The primary 40-candidate, concurrency-one condition "
                "has at least 199 successes from 200 attempts (error rate below one percent); "
                "every secondary condition has at least 20 successes. The controlled candidate "
                "cold start is reported separately."
            ),
            "throughput_claim_eligible": False,
            "scaling_claim_eligible": False,
            "concurrency_above_reserved_expected_to_expose_bound": [4, 8],
            "reserved_concurrency_is_a_cost_and_capacity_bound": True,
        },
        "limitations": [
            "No throughput claim.",
            "No scaling claim.",
            "Cold is one sample.",
            "Client timing includes network work.",
            "No held-out data is accessed.",
        ],
    }


def test_performance_report_requires_exact_matrix_and_recomputes_raw_aggregates() -> None:
    report = PerformanceReport.model_validate(performance_report())
    assert len(report.conditions) == 9
    assert report.totals.measured_request_count == 1800

    invalid = deepcopy(performance_report())
    invalid["conditions"][-1]["candidate_count"] = 20
    with pytest.raises(ValidationError, match="matrix is incomplete or duplicated"):
        PerformanceReport.model_validate(invalid)

    invalid = deepcopy(performance_report())
    invalid["conditions"][0]["measured"]["success_count"] = 199
    with pytest.raises(ValidationError, match="success/error totals"):
        PerformanceReport.model_validate(invalid)

    invalid = deepcopy(performance_report())
    invalid["lambda_configuration"]["benchmark_run_id"] = "github-999-attempt-1"
    with pytest.raises(ValidationError, match="identities differ"):
        PerformanceReport.model_validate(invalid)


@pytest.mark.parametrize(
    ("candidate_count", "concurrency", "phase", "success_count", "message"),
    [
        (40, 1, "measured", 198, "primary benchmark condition"),
        (10, 1, "measured", 19, "secondary benchmark condition"),
        (20, 4, "warmup", 0, "successful warmup"),
    ],
)
def test_performance_report_fails_closed_on_success_floors(
    candidate_count: int,
    concurrency: int,
    phase: str,
    success_count: int,
    message: str,
) -> None:
    invalid = deepcopy(performance_report())
    condition = next(
        item
        for item in invalid["conditions"]
        if item["candidate_count"] == candidate_count and item["offered_concurrency"] == concurrency
    )
    count = 10 if phase == "warmup" else 200
    condition[phase] = sample_summary(count, success_count=success_count)
    with pytest.raises(ValidationError, match=message):
        PerformanceReport.model_validate(invalid)


def test_performance_report_rejects_a_weakened_latency_claim() -> None:
    invalid = deepcopy(performance_report())
    invalid["interpretation"]["latency_claim"] = "Warm latency over successful responses."
    with pytest.raises(ValidationError, match="latency_claim"):
        PerformanceReport.model_validate(invalid)


def test_durable_evidence_json_schemas_match_their_pydantic_contracts() -> None:
    specifications = {
        "bundle_checksums.schema.json": ("search_rank.schemas.evidence", "BundleChecksums"),
        "release_manifest.schema.json": ("search_rank.schemas.evidence", "ReleaseManifest"),
        "evaluation_provenance.schema.json": (
            "search_rank.schemas.evidence",
            "EvaluationProvenance",
        ),
        "baseline_summary.schema.json": (
            "search_rank.schemas.publication",
            "BaselineSummary",
        ),
        "command_summary.schema.json": (
            "search_rank.schemas.publication",
            "CommandSummary",
        ),
        "curated_query_collection.schema.json": (
            "search_rank.schemas.publication",
            "CuratedQueryCollection",
        ),
        "heldout_access_counter.schema.json": (
            "search_rank.schemas.publication",
            "HeldoutAccessCounter",
        ),
        "processing_job_evidence.schema.json": (
            "search_rank.schemas.publication",
            "ProcessingJobEvidence",
        ),
        "publication_evidence.schema.json": (
            "search_rank.schemas.publication",
            "PublicationEvidence",
        ),
        "release_summary.schema.json": (
            "search_rank.schemas.publication",
            "ReleaseSummary",
        ),
        "trial_selection_binding.schema.json": (
            "search_rank.schemas.publication",
            "TrialSelectionBinding",
        ),
        "trial_selection_verification.schema.json": (
            "search_rank.schemas.publication",
            "TrialSelectionVerification",
        ),
        "candidate_release_inputs.schema.json": (
            "search_rank.schemas.workflow",
            "CandidateReleaseInputs",
        ),
        "training_image_provenance.schema.json": (
            "search_rank.schemas.workflow",
            "TrainingImageProvenance",
        ),
        "cloud_training_job_evidence.schema.json": (
            "search_rank.schemas.workflow",
            "CloudTrainingJobEvidence",
        ),
        "protected_financial_snapshot.schema.json": (
            "search_rank.schemas.workflow",
            "ProtectedFinancialSnapshot",
        ),
        "training_cost_preflight.schema.json": (
            "search_rank.schemas.workflow",
            "TrainingCostPreflight",
        ),
        "sagemaker_managed_spot_quota_preflight.schema.json": (
            "search_rank.schemas.workflow",
            "SageMakerManagedSpotQuotaPreflight",
        ),
        "sagemaker_processing_quota_preflight.schema.json": (
            "search_rank.schemas.workflow",
            "SageMakerProcessingQuotaPreflight",
        ),
        "evaluation_cost_preflight.schema.json": (
            "search_rank.schemas.workflow",
            "EvaluationCostPreflight",
        ),
        "benchmark_cost_preflight.schema.json": (
            "search_rank.schemas.workflow",
            "BenchmarkCostPreflight",
        ),
        "deployment_evidence.schema.json": (
            "search_rank.schemas.workflow",
            "DeploymentEvidence",
        ),
        "automatic_deployment_rollback.schema.json": (
            "search_rank.schemas.workflow",
            "AutomaticDeploymentRollback",
        ),
        "manual_rollback_evidence.schema.json": (
            "search_rank.schemas.workflow",
            "ManualRollbackEvidence",
        ),
        "performance_report.schema.json": (
            "search_rank.schemas.workflow",
            "PerformanceReport",
        ),
        "benchmark_lambda_configuration.schema.json": (
            "search_rank.schemas.workflow",
            "BenchmarkLambdaConfiguration",
        ),
        "performance_validation.schema.json": (
            "search_rank.schemas.workflow",
            "PerformanceValidation",
        ),
    }
    for filename, (module_name, model_name) in specifications.items():
        document = json.loads((Path("schemas/json") / filename).read_text(encoding="utf-8"))
        assert document.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
        assert document.pop("$id").endswith("/" + filename)
        model = getattr(importlib.import_module(module_name), model_name)
        assert document == model.model_json_schema(), filename
        assert document.get("additionalProperties") is False
