#!/usr/bin/env python3
"""Assemble one immutable, public-safe release record from validated handoffs.

Local handoffs retain private routing values needed by downstream workflows. This
module validates their exact shapes but selects every public field explicitly;
handoffs are never copied into the committed record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from search_rank.evaluation.report import validate_report_consistency
from search_rank.schemas.evaluation import EvaluationReport
from search_rank.schemas.evidence import BundleChecksums, EvaluationProvenance
from search_rank.schemas.performance import ColdStartEvidence
from search_rank.schemas.publication import ReleaseSummary
from search_rank.schemas.release import PromotionPointer
from search_rank.schemas.workflow import (
    BenchmarkCostPreflight,
    BenchmarkLambdaConfiguration,
    DeploymentEvidence,
    ManualRollbackEvidence,
    PerformanceReport,
    PerformanceValidation,
)

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[1-9][0-9]*$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,127}$")
CLOUDFRONT = re.compile(r"^https://[a-z0-9-]+\.cloudfront\.net$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_JSON_BYTES = 16 * 1024 * 1024

BASE_KEYS = {"schema_version", "stage", "frozen_git_sha", "github_run_id"}
DEPLOY_KEYS = BASE_KEYS | {
    "release_id",
    "model_id",
    "serving_image_digest",
    "previous_lambda_version",
    "production_lambda_version",
    "promoted_pointer_version_id",
    "previous_release_id",
    "previous_model_id",
    "public_origin",
    "controlled_cold_start_ms",
    "candidate_gate_error_rate",
    "candidate_gate_p95_ms",
}
HANDOFF_KEYS = {
    "release": BASE_KEYS
    | {
        "release_id",
        "model_id",
        "bundle_s3_key",
        "evaluation_report_id",
        "release_decision",
        "gate_passed",
        "evaluated_candidate_model_id",
        "previous_release_id",
        "previous_model_id",
        "previous_pointer_version_id",
        "candidate_metric",
        "strongest_baseline_id",
        "strongest_baseline_metric",
        "candidate_minus_baseline",
        "paired_differences",
        "release_gate_reasons",
        "evaluation_image_digest",
        "trial_selection_id",
        "trial_selection_sha256",
    },
    "deploy-winner": DEPLOY_KEYS,
    "deploy-baseline": DEPLOY_KEYS,
    "benchmark": BASE_KEYS
    | {
        "benchmark_run_id",
        "release_id",
        "model_id",
        "public_origin",
        "published_prefix",
        "measured_request_count",
        "measured_success_count",
        "measured_error_count",
        "measured_throttle_count",
        "primary_end_to_end_latency_ms",
        "primary_model_latency_ms",
        "primary_serialization_latency_ms",
        "controlled_cold_start_ms",
        "controlled_cold_init_ms",
        "controlled_cold_max_memory_mb",
    },
    "rollback": BASE_KEYS
    | {
        "restored_release_id",
        "restored_model_id",
        "from_lambda_version",
        "to_lambda_version",
        "restored_pointer_version_id",
    },
    "redeploy-winner": DEPLOY_KEYS,
}
LATENCY_KEYS = {"p50", "p95", "p99", "mean", "minimum", "maximum"}
BENCHMARK_DURABLE_FILES = {
    "controlled-cold-start.json",
    "cost-preflight.json",
    "lambda-configuration.json",
    "performance-report.json",
    "validation.json",
}

ModelT = TypeVar("ModelT", bound=BaseModel)

FORBIDDEN_KEY_PARTS = (
    "account_id",
    "arn",
    "authorization",
    "bucket",
    "credit_balance",
    "email",
    "etag",
    "function_name",
    "job_name",
    "lambda_version",
    "path",
    "pointer_version",
    "prefix",
    "receipt",
    "s3",
    "secret",
    "signature",
    "signed",
    "token",
)
PRIVATE_TEXT_PATTERNS = (
    re.compile(r"arn:aws", re.IGNORECASE),
    re.compile(r"s3://", re.IGNORECASE),
    re.compile(r"\.amazonaws\.com", re.IGNORECASE),
    re.compile(r"x-amz-", re.IGNORECASE),
    re.compile(r"(?:^|[^0-9])[0-9]{12}(?:[^0-9]|$)"),
    re.compile(r"^[A-Za-z]:[\\/]"),
    re.compile(r"(?:^|/)\.\.(?:/|$)"),
    re.compile(r"(?:^|/)(?:home|Users)/", re.IGNORECASE),
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
)


class ReleaseEvidenceError(ValueError):
    """Evidence cannot safely support the public release record."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseEvidenceError(message)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "JSON input contains duplicate keys")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    _require(path.is_file() and not path.is_symlink(), "required evidence is absent or linked")
    _require(path.stat().st_size <= MAX_JSON_BYTES, "JSON evidence exceeds the size bound")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseEvidenceError("JSON evidence is unavailable or malformed") from error


def _load_text(path: Path, *, maximum_bytes: int = 4096) -> str:
    _require(path.is_file() and not path.is_symlink(), "required evidence is absent or linked")
    _require(path.stat().st_size <= maximum_bytes, "text evidence exceeds the size bound")
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise ReleaseEvidenceError("text evidence is unavailable or malformed") from error


def _model(path: Path, model_type: type[ModelT], label: str) -> ModelT:
    try:
        return model_type.model_validate(_load_json(path))
    except ValidationError as error:
        raise ReleaseEvidenceError(f"{label} violates its typed contract") from error


def _object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} must be an object")
    assert isinstance(value, dict)
    _require(set(value) == keys, f"{label} does not have the exact expected fields")
    return value


def _text(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} must be a non-empty string")
    assert isinstance(value, str)
    return value


def _identifier(value: Any, label: str) -> str:
    text_value = _text(value, label)
    _require(SAFE_ID.fullmatch(text_value) is not None, f"{label} is not a public-safe identifier")
    return text_value


def _digest(value: Any, label: str) -> str:
    text_value = _text(value, label)
    _require(SHA256.fullmatch(text_value) is not None, f"{label} is not a SHA-256 digest")
    return text_value


def _number(value: Any, label: str, minimum: float | None = None) -> float:
    _require(type(value) in {int, float}, f"{label} must be numeric")
    result = float(value)
    _require(math.isfinite(result), f"{label} must be finite")
    if minimum is not None:
        _require(result >= minimum, f"{label} is below its minimum")
    return result


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{label} must be a bounded integer")
    assert isinstance(value, int)
    return value


def _sha256(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), "required evidence is absent or linked")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: str, label: str) -> datetime:
    _require(UTC_TIMESTAMP.fullmatch(value) is not None, f"{label} must be second-precision UTC")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise ReleaseEvidenceError(f"{label} is invalid") from error


def _stage_root(root: Path, sha: str, stage: str) -> Path:
    _require(FULL_SHA.fullmatch(sha) is not None, "evidence SHA is invalid")
    _require(stage in HANDOFF_KEYS, "evidence stage is unsupported")
    _require(root.is_dir() and not root.is_symlink(), "evidence root is absent or linked")
    root = root.resolve(strict=True)
    sha_path = root / sha
    _require(
        sha_path.is_dir() and not sha_path.is_symlink(), "evidence SHA root is absent or linked"
    )
    sha_root = sha_path.resolve(strict=True)
    stage_path = sha_root / stage
    _require(
        stage_path.is_dir() and not stage_path.is_symlink(), "evidence stage is absent or linked"
    )
    stage_root = stage_path.resolve(strict=True)
    _require(root in sha_root.parents and sha_root in stage_root.parents, "evidence path escaped")
    return stage_root


def _handoff(root: Path, sha: str, stage: str) -> dict[str, Any]:
    payload = _object(
        _load_json(_stage_root(root, sha, stage) / "_handoff.json"),
        HANDOFF_KEYS[stage],
        f"{stage} handoff",
    )
    _require(payload["schema_version"] == "1.0.0", "handoff schema version differs")
    _require(
        payload["stage"] == stage and payload["frozen_git_sha"] == sha, "handoff identity differs"
    )
    run_id = _text(payload["github_run_id"], "workflow run ID")
    _require(RUN_ID.fullmatch(run_id) is not None, "workflow run ID is invalid")
    return payload


def _latency(value: Any, label: str) -> dict[str, float]:
    value = _object(value, LATENCY_KEYS, label)
    numbers = {key: _number(value[key], f"{label}.{key}", 0) for key in LATENCY_KEYS}
    _require(
        numbers["minimum"]
        <= numbers["p50"]
        <= numbers["p95"]
        <= numbers["p99"]
        <= numbers["maximum"],
        f"{label} is not monotonic",
    )
    _require(
        numbers["minimum"] <= numbers["mean"] <= numbers["maximum"], f"{label} mean is invalid"
    )
    return {key: numbers[key] for key in ("p50", "p95", "p99", "mean", "minimum", "maximum")}


def _require_handoff_values(
    handoff: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    for key, expected_value in expected.items():
        _require(handoff[key] == expected_value, f"{label} {key} differs from typed evidence")


def _release_files(
    evidence_root: Path, source_sha: str
) -> tuple[
    dict[str, Any],
    EvaluationReport,
    EvaluationProvenance,
    ReleaseSummary,
    PromotionPointer,
    PromotionPointer,
    Path,
]:
    release_root = _stage_root(evidence_root, source_sha, "release")
    handoff = _handoff(evidence_root, source_sha, "release")
    report = _model(release_root / "evaluation-report.json", EvaluationReport, "evaluation report")
    provenance = _model(
        release_root / "evaluation-provenance.json",
        EvaluationProvenance,
        "evaluation provenance",
    )
    summary = _model(release_root / "release-summary.json", ReleaseSummary, "release summary")
    pointer = _model(
        release_root / "promotion-pointer.json", PromotionPointer, "release promotion pointer"
    )
    previous = _model(
        release_root / "previous-pointer.json", PromotionPointer, "release previous pointer"
    )
    try:
        validate_report_consistency(report)
    except ValueError as error:
        raise ReleaseEvidenceError("evaluation report cross-field consistency failed") from error

    _require(pointer.previous is not None, "release promotion pointer lacks its prior release")
    assert pointer.previous is not None
    _require(
        pointer.git_sha == summary.code_commit == provenance.evaluation_git_sha == source_sha,
        "release source identities differ",
    )
    _require(
        report.report_id == summary.report_id == pointer.release_id == pointer.evaluation_report_id,
        "release report identities differ",
    )
    _require(
        report.run_id == summary.run_id
        and report.candidate_model_id == summary.candidate_model_id
        and report.baseline_model_ids == summary.baseline_model_ids,
        "release evaluation identities differ",
    )
    _require(
        report.primary_metric == summary.primary_metric
        and report.paired_differences == summary.paired_differences,
        "release metric evidence differs",
    )
    _require(
        report.test_access_count == summary.test_access_count == provenance.test_access_count
        and summary.clean_evaluation_count == provenance.independent_evaluation_count
        and summary.source_evaluations == provenance.source_evaluations
        and summary.evaluation_config_hash == provenance.config_hash,
        "release clean-evaluation binding differs",
    )
    gate = report.release_gate_results
    _require(
        gate.passed == summary.gate_passed
        and gate.decision == summary.promotion_decision
        and gate.promoted_model_id == summary.promoted_model_id == pointer.model_id,
        "release gate evidence differs",
    )
    _require(
        pointer.gate_passed == gate.passed
        and pointer.release_decision == gate.decision
        and pointer.evaluated_candidate_model_id == report.candidate_model_id,
        "release pointer gate evidence differs",
    )
    _require(
        pointer.previous.release_id == previous.release_id
        and pointer.previous.model_id == previous.model_id,
        "release prior pointer identity differs",
    )
    _require(
        provenance.report_id == report.report_id
        and provenance.split == report.split
        and provenance.strongest_baseline_id == report.primary_metric.strongest_baseline_id
        and provenance.evaluation_image_digest == summary.evaluation_image_digest,
        "release provenance differs from evaluation",
    )
    paired = [item.model_dump(mode="json") for item in report.paired_differences]
    expected = {
        "release_id": pointer.release_id,
        "model_id": pointer.model_id,
        "bundle_s3_key": pointer.bundle_s3_key,
        "evaluation_report_id": pointer.evaluation_report_id,
        "release_decision": gate.decision,
        "gate_passed": gate.passed,
        "evaluated_candidate_model_id": report.candidate_model_id,
        "previous_release_id": previous.release_id,
        "previous_model_id": previous.model_id,
        "previous_pointer_version_id": pointer.previous.pointer_version_id,
        "candidate_metric": report.primary_metric.candidate_value,
        "strongest_baseline_id": report.primary_metric.strongest_baseline_id,
        "strongest_baseline_metric": report.primary_metric.strongest_baseline_value,
        "candidate_minus_baseline": report.primary_metric.candidate_minus_baseline,
        "paired_differences": paired,
        "release_gate_reasons": list(gate.reasons),
        "evaluation_image_digest": summary.evaluation_image_digest,
        "trial_selection_id": summary.trial_selection_id,
        "trial_selection_sha256": summary.trial_selection_sha256,
    }
    _require_handoff_values(handoff, expected, "release handoff")
    return handoff, report, provenance, summary, pointer, previous, release_root


def _deployment_files(
    evidence_root: Path,
    deployment_sha: str,
    source_sha: str,
    stage: str,
) -> tuple[dict[str, Any], DeploymentEvidence, PromotionPointer, PromotionPointer, Path]:
    stage_root = _stage_root(evidence_root, deployment_sha, stage)
    handoff = _handoff(evidence_root, deployment_sha, stage)
    deployment = _model(
        stage_root / "deployment-evidence.json", DeploymentEvidence, f"{stage} deployment evidence"
    )
    pointer = _model(
        stage_root / "promotion-pointer.json", PromotionPointer, f"{stage} promotion pointer"
    )
    previous = _model(
        stage_root / "previous-promotion-pointer.json",
        PromotionPointer,
        f"{stage} previous pointer",
    )
    origin = deployment.production_api_smoke.base_url_origin
    _require(deployment.code_commit == deployment_sha, f"{stage} deployment source differs")
    _require(pointer.git_sha == source_sha, f"{stage} release pointer source differs")
    _require(previous.git_sha == source_sha, f"{stage} prior pointer source differs")
    _require(
        pointer.release_id == deployment.release_id and pointer.model_id == deployment.model_id,
        f"{stage} pointer and deployment identity differ",
    )
    _require(CLOUDFRONT.fullmatch(origin) is not None, f"{stage} public origin is not CloudFront")
    expected = {
        "release_id": deployment.release_id,
        "model_id": deployment.model_id,
        "serving_image_digest": deployment.serving_image_digest,
        "previous_lambda_version": deployment.previous_lambda_version,
        "production_lambda_version": deployment.production_lambda_version,
        "promoted_pointer_version_id": deployment.promoted_pointer_version_id,
        "previous_release_id": previous.release_id,
        "previous_model_id": previous.model_id,
        "public_origin": origin,
        "controlled_cold_start_ms": (
            deployment.controlled_cold_start.first_request.end_to_end_latency_ms
        ),
        "candidate_gate_error_rate": deployment.candidate_api_gate.error_rate,
        "candidate_gate_p95_ms": deployment.candidate_api_gate.end_to_end_latency_ms.p95,
    }
    _require_handoff_values(handoff, expected, f"{stage} handoff")
    return handoff, deployment, pointer, previous, stage_root


def _rollback_files(
    evidence_root: Path, deployment_sha: str
) -> tuple[dict[str, Any], ManualRollbackEvidence, Path]:
    rollback_root = _stage_root(evidence_root, deployment_sha, "rollback")
    handoff = _handoff(evidence_root, deployment_sha, "rollback")
    evidence = _model(
        rollback_root / "rollback-evidence.json", ManualRollbackEvidence, "rollback evidence"
    )
    _require(evidence.workflow_commit == deployment_sha, "rollback source identity differs")
    _require_handoff_values(
        handoff,
        {
            "restored_release_id": evidence.restored_release_id,
            "restored_model_id": evidence.restored_model_id,
            "from_lambda_version": evidence.from_lambda_version,
            "to_lambda_version": evidence.to_lambda_version,
            "restored_pointer_version_id": evidence.restored_pointer_version_id,
        },
        "rollback handoff",
    )
    return handoff, evidence, rollback_root


def _benchmark_files(
    benchmark_root: Path,
    benchmark: Mapping[str, Any],
    source_sha: str,
    deployment_sha: str,
    generated_at: datetime,
    release_pointer: PromotionPointer,
    deployment: DeploymentEvidence,
) -> tuple[dict[str, str], str, str, PerformanceReport]:
    report_path = benchmark_root / "performance-report.json"
    report = _model(report_path, PerformanceReport, "benchmark report")
    validation = _model(
        benchmark_root / "validation.json", PerformanceValidation, "benchmark validation"
    )
    cost = _model(
        benchmark_root / "cost-preflight.json", BenchmarkCostPreflight, "benchmark cost preflight"
    )
    lambda_config = _model(
        benchmark_root / "lambda-configuration.json",
        BenchmarkLambdaConfiguration,
        "benchmark Lambda configuration",
    )
    cold = _model(
        benchmark_root / "controlled-cold-start.json",
        ColdStartEvidence,
        "benchmark cold-start evidence",
    )
    checksum_path = benchmark_root / "evidence-checksums.json"
    checksums = _model(checksum_path, BundleChecksums, "benchmark checksum inventory")
    _require(
        set(checksums.files) == BENCHMARK_DURABLE_FILES,
        "benchmark checksum inventory differs",
    )
    for relative, expected_digest in checksums.files.items():
        _require(
            _sha256(benchmark_root / relative) == expected_digest,
            "benchmark durable artifact checksum differs",
        )
    checksum_sha = _sha256(checksum_path)
    expected_prefix = (
        f"public/{report.identifiers.release_id}/performance/runs/"
        f"{report.identifiers.benchmark_run_id}/sha256-{checksum_sha.removeprefix('sha256:')}/"
    )
    _require(
        _load_text(benchmark_root / "published-prefix.txt") == expected_prefix
        and benchmark["published_prefix"] == expected_prefix,
        "benchmark publication prefix differs",
    )

    ids = report.identifiers
    binding = report.release_binding
    report_sha = _sha256(report_path)
    _require(ids.evidence_mode == "verified", "benchmark evidence mode differs")
    _require(ids.release_git_sha == source_sha, "release source binding differs")
    _require(ids.benchmark_harness_git_sha == deployment_sha, "benchmark source binding differs")
    _require(ids.region == "us-east-1", "benchmark region differs")
    _require(
        ids.release_id == deployment.release_id == release_pointer.release_id
        and ids.model_id == deployment.model_id == release_pointer.model_id,
        "benchmark release identity differs from deployment",
    )
    _require(
        ids.public_origin == deployment.production_api_smoke.base_url_origin,
        "benchmark public origin differs from deployment",
    )
    _require(
        binding.bundle_s3_key == release_pointer.bundle_s3_key
        and binding.promotion_pointer_version_id == deployment.promoted_pointer_version_id,
        "benchmark release pointer binding differs",
    )
    _require(
        report.lambda_configuration == lambda_config
        and report.controlled_cold_start == cold == deployment.controlled_cold_start,
        "benchmark runtime evidence differs from deployment",
    )
    _require(
        lambda_config.function_version == deployment.production_lambda_version,
        "benchmark Lambda version differs from deployment",
    )
    _require(
        (
            cost.benchmark_run_id,
            cost.release_id,
            cost.model_id,
            cost.region,
            cost.public_origin,
        )
        == (
            ids.benchmark_run_id,
            ids.release_id,
            ids.model_id,
            ids.region,
            ids.public_origin,
        ),
        "benchmark cost preflight identity differs",
    )
    _require(
        validation.performance_report_sha256 == report_sha,
        "benchmark report hash differs",
    )
    _require(
        (
            validation.benchmark_run_id,
            validation.release_id,
            validation.model_id,
            validation.measured_request_count,
        )
        == (
            ids.benchmark_run_id,
            ids.release_id,
            ids.model_id,
            report.totals.measured_request_count,
        ),
        "benchmark validation identity differs",
    )
    primary = next(
        condition
        for condition in report.conditions
        if condition.candidate_count == report.protocol.primary_latency_candidate_count
        and condition.offered_concurrency == report.protocol.primary_latency_offered_concurrency
    )
    secondary = [condition for condition in report.conditions if condition is not primary]
    _require(
        validation.minimum_warmup_condition_success_count
        == min(condition.warmup.success_count for condition in report.conditions)
        and validation.primary_latency_condition_success_count == primary.measured.success_count
        and validation.minimum_secondary_condition_success_count
        == min(condition.measured.success_count for condition in secondary),
        "benchmark validation success floors differ",
    )
    _require(
        cost.checked_at <= report.started_at
        and lambda_config.checked_at <= report.started_at
        and cold.measured_at <= report.started_at
        and report.completed_at <= validation.validated_at <= generated_at,
        "benchmark evidence timestamps are not causally ordered",
    )
    end_to_end = primary.measured.end_to_end_latency_ms
    model = primary.measured.model_latency_ms
    serialization = primary.measured.serialization_latency_ms
    _require(
        end_to_end is not None and model is not None and serialization is not None,
        "primary benchmark latencies are absent",
    )
    assert end_to_end is not None and model is not None and serialization is not None
    expected_handoff = {
        "benchmark_run_id": ids.benchmark_run_id,
        "release_id": ids.release_id,
        "model_id": ids.model_id,
        "public_origin": ids.public_origin,
        "measured_request_count": report.totals.measured_request_count,
        "measured_success_count": report.totals.measured_success_count,
        "measured_error_count": report.totals.measured_error_count,
        "measured_throttle_count": report.totals.measured_throttle_count,
        "primary_end_to_end_latency_ms": end_to_end.model_dump(mode="json"),
        "primary_model_latency_ms": model.model_dump(mode="json"),
        "primary_serialization_latency_ms": serialization.model_dump(mode="json"),
        "controlled_cold_start_ms": cold.first_request.end_to_end_latency_ms,
        "controlled_cold_init_ms": cold.lambda_report.init_duration_ms,
        "controlled_cold_max_memory_mb": cold.lambda_report.max_memory_used_mb,
    }
    _require_handoff_values(benchmark, expected_handoff, "benchmark handoff")
    return (
        {
            "release_manifest": binding.release_manifest_sha256,
            "public_evidence": binding.public_evidence_sha256,
            "bundle_checksums": binding.bundle_checksums_sha256,
            "deployment_evidence": binding.deployment_evidence_sha256,
            "dataset_manifest": ids.dataset_manifest_hash,
            "model_artifact": ids.model_artifact_checksum,
        },
        report_sha,
        checksum_sha,
        report,
    )


def _public_only(value: Any, path: tuple[str, ...] = ()) -> None:
    if type(value) is dict:
        for key, child in value.items():
            _require(type(key) is str, "public evidence contains a non-string key")
            _require(
                not any(part in key.casefold() for part in FORBIDDEN_KEY_PARTS),
                "public evidence contains a private field",
            )
            _public_only(child, (*path, key))
        return
    if type(value) is list:
        for index, child in enumerate(value):
            _public_only(child, (*path, str(index)))
        return
    if type(value) is str:
        if value.startswith(("http://", "https://")):
            _require(
                CLOUDFRONT.fullmatch(value) is not None, "public evidence contains an unsafe URL"
            )
        account_exempt = (
            "workflow_run_ids" in path
            or SHA256.fullmatch(value) is not None
            or FULL_SHA.fullmatch(value) is not None
        )
        for pattern in PRIVATE_TEXT_PATTERNS:
            if account_exempt and pattern.pattern.startswith("(?:^|[^0-9])"):
                continue
            _require(pattern.search(value) is None, "public evidence contains private text")
        _require(
            "\\" not in value and not value.startswith("/"),
            "public evidence contains a private path",
        )
        return
    _require(value is None or type(value) in {bool, int, float}, "public evidence type is unsafe")
    if type(value) is float:
        _require(math.isfinite(value), "public evidence contains a non-finite number")


def assemble(
    evidence_root: Path,
    source_sha: str,
    deployment_sha: str,
    *,
    generated_at: str,
    public_demo_expires_at: str,
) -> dict[str, Any]:
    """Purely derive one strict public record from a complete validated release chain."""

    generated = _utc(generated_at, "generated_at")
    expires = _utc(public_demo_expires_at, "public_demo_expires_at")
    _require(
        generated < expires <= generated + timedelta(hours=24), "public demo expiry is invalid"
    )
    (
        release,
        evaluation,
        evaluation_provenance,
        release_summary,
        release_pointer,
        previous_pointer,
        release_root,
    ) = _release_files(evidence_root, source_sha)
    release_prior = release_pointer.previous
    _require(release_prior is not None, "release promotion pointer lacks its prior release")
    assert release_prior is not None
    baseline, baseline_deployment, baseline_pointer, baseline_previous, baseline_root = (
        _deployment_files(
            evidence_root,
            deployment_sha,
            source_sha,
            "deploy-baseline",
        )
    )
    deploy, deployment, deploy_pointer, deploy_previous, deploy_root = _deployment_files(
        evidence_root,
        deployment_sha,
        source_sha,
        "deploy-winner",
    )
    benchmark = _handoff(evidence_root, deployment_sha, "benchmark")
    rollback, rollback_evidence, rollback_root = _rollback_files(evidence_root, deployment_sha)
    redeploy, redeployment, redeploy_pointer, redeploy_previous, redeploy_root = _deployment_files(
        evidence_root,
        deployment_sha,
        source_sha,
        "redeploy-winner",
    )

    _require(
        baseline_deployment.release_id == previous_pointer.release_id
        and baseline_deployment.model_id == previous_pointer.model_id,
        "baseline deployment differs from the release rollback target",
    )
    _require(
        baseline_previous.release_id == previous_pointer.release_id
        and baseline_previous.model_id == previous_pointer.model_id,
        "baseline deployment prior identity differs",
    )
    _require(
        baseline_deployment.promoted_pointer_version_id == release_prior.pointer_version_id,
        "baseline deployment pointer version differs from the release rollback target",
    )
    _require(
        deployment.release_id == release_pointer.release_id
        and deployment.model_id == release_pointer.model_id,
        "winner deployment differs from the held-out decision",
    )
    _require(
        deploy_previous.release_id == baseline_deployment.release_id
        and deploy_previous.model_id == baseline_deployment.model_id,
        "winner deployment prior identity differs from the baseline deployment",
    )
    _require(
        deployment.previous_lambda_version == baseline_deployment.production_lambda_version,
        "winner deployment prior Lambda version differs from the baseline deployment",
    )
    _require(
        rollback_evidence.restored_release_id == baseline_deployment.release_id
        and rollback_evidence.restored_model_id == baseline_deployment.model_id
        and rollback_evidence.from_lambda_version == deployment.production_lambda_version
        and rollback_evidence.to_lambda_version == baseline_deployment.production_lambda_version,
        "rollback does not restore the validated baseline deployment",
    )
    _require(
        redeployment.release_id == deployment.release_id
        and redeployment.model_id == deployment.model_id
        and redeployment.serving_image_digest == deployment.serving_image_digest
        and redeployment.production_api_smoke.base_url_origin
        == deployment.production_api_smoke.base_url_origin,
        "redeployment differs from the immutable winning release",
    )
    _require(
        redeploy_previous.release_id == baseline_deployment.release_id
        and redeploy_previous.model_id == baseline_deployment.model_id
        and redeployment.previous_lambda_version == baseline_deployment.production_lambda_version,
        "redeployment does not start from the restored baseline",
    )
    _require(
        redeployment.production_lambda_version != deployment.production_lambda_version,
        "redeployment did not publish a fresh Lambda version",
    )
    _require(
        baseline_deployment.production_api_smoke.base_url_origin
        == deployment.production_api_smoke.base_url_origin
        == redeployment.production_api_smoke.base_url_origin,
        "deployment stages use different public origins",
    )

    baseline_pointer_sha = _sha256(baseline_root / "promotion-pointer.json")
    release_previous_pointer_sha = _sha256(release_root / "previous-pointer.json")
    release_pointer_sha = _sha256(release_root / "promotion-pointer.json")
    deploy_pointer_sha = _sha256(deploy_root / "promotion-pointer.json")
    redeploy_pointer_sha = _sha256(redeploy_root / "promotion-pointer.json")
    _require(
        baseline_pointer_sha == release_previous_pointer_sha,
        "baseline pointer bytes differ from the held-out rollback target",
    )
    _require(
        _sha256(baseline_root / "previous-promotion-pointer.json") == baseline_pointer_sha
        and _sha256(deploy_root / "previous-promotion-pointer.json") == baseline_pointer_sha
        and _sha256(redeploy_root / "previous-promotion-pointer.json") == baseline_pointer_sha,
        "deployment prior pointer bytes differ from the validated baseline",
    )
    _require(
        release_pointer_sha == deploy_pointer_sha == redeploy_pointer_sha,
        "winner promotion pointer bytes differ across deployment and redeployment",
    )
    _require(
        baseline_pointer == previous_pointer
        and deploy_pointer == release_pointer
        and redeploy_pointer == release_pointer,
        "typed deployment pointers differ from the release decisions",
    )

    benchmark_root = _stage_root(evidence_root, deployment_sha, "benchmark")
    bound, benchmark_report_sha, benchmark_checksums_sha, performance = _benchmark_files(
        benchmark_root,
        benchmark,
        source_sha,
        deployment_sha,
        generated,
        release_pointer,
        deployment,
    )
    deployment_evidence_sha = _sha256(deploy_root / "deployment-evidence.json")
    _require(deployment_evidence_sha == bound["deployment_evidence"], "deployment hash differs")
    _require(
        bound["dataset_manifest"] == evaluation_provenance.dataset_manifest_hash,
        "benchmark dataset differs from held-out evaluation provenance",
    )
    _require(evaluation.created_at <= generated, "release evidence postdates assembly")

    primary = next(
        condition
        for condition in performance.conditions
        if condition.candidate_count == performance.protocol.primary_latency_candidate_count
        and condition.offered_concurrency
        == performance.protocol.primary_latency_offered_concurrency
    )
    end_to_end = primary.measured.end_to_end_latency_ms
    model_latency = primary.measured.model_latency_ms
    serialization = primary.measured.serialization_latency_ms
    assert end_to_end is not None and model_latency is not None and serialization is not None
    paired = [item.model_dump(mode="json") for item in evaluation.paired_differences]
    gate = evaluation.release_gate_results

    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "evidence_status": "verified_measurement",
        "generated_at": generated_at,
        "public_demo_expires_at": public_demo_expires_at,
        "evidence_mode": "verified",
        "release_id": _identifier(release_pointer.release_id, "release ID"),
        "workflow_run_ids": {
            stage.replace("-", "_"): handoff["github_run_id"]
            for stage, handoff in (
                ("release", release),
                ("deploy-baseline", baseline),
                ("deploy-winner", deploy),
                ("benchmark", benchmark),
                ("rollback", rollback),
                ("redeploy-winner", redeploy),
            )
        },
        "identities": {
            "release_git_sha": source_sha,
            "deployment_git_sha": deployment_sha,
            "dataset_manifest_sha256": bound["dataset_manifest"],
            "model_artifact_sha256": bound["model_artifact"],
            "evaluation_image_digest": _digest(
                release_summary.evaluation_image_digest, "evaluation image"
            ),
            "serving_image_digest": _digest(deployment.serving_image_digest, "serving image"),
            "trial_selection_id": _identifier(
                release_summary.trial_selection_id, "trial selection ID"
            ),
            "trial_selection_sha256": _digest(
                release_summary.trial_selection_sha256, "trial selection digest"
            ),
        },
        "release_gate": {
            "passed": gate.passed,
            "decision": gate.decision,
            "promoted_model_id": _identifier(gate.promoted_model_id, "promoted model ID"),
            "evaluated_candidate_model_id": _identifier(
                evaluation.candidate_model_id, "evaluated candidate model ID"
            ),
            "strongest_baseline_model_id": _identifier(
                evaluation.primary_metric.strongest_baseline_id, "strongest baseline model ID"
            ),
        },
        "metrics": {
            "primary_metric": "graded_ndcg@10",
            "candidate_value": evaluation.primary_metric.candidate_value,
            "strongest_baseline_value": evaluation.primary_metric.strongest_baseline_value,
            "candidate_minus_baseline": evaluation.primary_metric.candidate_minus_baseline,
            "paired_differences": paired,
        },
        "deployment": {
            "public_url": deployment.production_api_smoke.base_url_origin,
            "smoke_tests_passed": True,
            "candidate_gate_error_rate": deployment.candidate_api_gate.error_rate,
            "candidate_gate_p95_ms": deployment.candidate_api_gate.end_to_end_latency_ms.p95,
            "controlled_cold_start_ms": (
                deployment.controlled_cold_start.first_request.end_to_end_latency_ms
            ),
        },
        "benchmark": {
            "protocol": performance.protocol.measurement_class,
            "primary_candidate_count": performance.protocol.primary_latency_candidate_count,
            "primary_offered_concurrency": (
                performance.protocol.primary_latency_offered_concurrency
            ),
            "measured_request_count": performance.totals.measured_request_count,
            "measured_success_count": performance.totals.measured_success_count,
            "measured_error_count": performance.totals.measured_error_count,
            "measured_throttle_count": performance.totals.measured_throttle_count,
            "primary_end_to_end_latency_ms": _latency(
                end_to_end.model_dump(mode="json"), "end-to-end latency"
            ),
            "primary_model_latency_ms": _latency(
                model_latency.model_dump(mode="json"), "model latency"
            ),
            "primary_serialization_latency_ms": _latency(
                serialization.model_dump(mode="json"), "serialization latency"
            ),
            "controlled_cold_start_ms": (
                performance.controlled_cold_start.first_request.end_to_end_latency_ms
            ),
            "controlled_cold_init_ms": performance.controlled_cold_start.lambda_report.init_duration_ms,
            "controlled_cold_max_memory_mb": (
                performance.controlled_cold_start.lambda_report.max_memory_used_mb
            ),
            "throughput_claim_eligible": performance.interpretation.throughput_claim_eligible,
            "scaling_claim_eligible": performance.interpretation.scaling_claim_eligible,
        },
        "rollback": {
            "verified": True,
            "restored_release_id": _identifier(
                rollback_evidence.restored_release_id, "restored release"
            ),
            "restored_model_id": _identifier(rollback_evidence.restored_model_id, "restored model"),
            "smoke_tests_passed": True,
        },
        "redeployment": {
            "verified": True,
            "release_id": _identifier(redeployment.release_id, "redeployed release"),
            "model_id": _identifier(redeployment.model_id, "redeployed model"),
            "exact_winner_redeployed": True,
            "fresh_runtime_revision_published": True,
            "public_url": redeployment.production_api_smoke.base_url_origin,
        },
        "artifact_sha256": {
            "release_manifest": bound["release_manifest"],
            "public_evidence": bound["public_evidence"],
            "bundle_checksums": bound["bundle_checksums"],
            "heldout_evaluation_report": _sha256(release_root / "evaluation-report.json"),
            "heldout_evaluation_provenance": _sha256(release_root / "evaluation-provenance.json"),
            "baseline_deployment_evidence": _sha256(baseline_root / "deployment-evidence.json"),
            "deployment_evidence": deployment_evidence_sha,
            "promotion_pointer": release_pointer_sha,
            "benchmark_performance_report": benchmark_report_sha,
            "benchmark_evidence_checksums": benchmark_checksums_sha,
            "rollback_evidence": _sha256(rollback_root / "rollback-evidence.json"),
            "redeployment_evidence": _sha256(redeploy_root / "deployment-evidence.json"),
        },
    }
    _public_only(payload)
    return payload


def write_immutable(payload: Mapping[str, Any], output_dir: Path) -> Path:
    """Atomically write `<release-id>.json`, refusing a different replacement."""

    public_payload = dict(payload)
    _public_only(public_payload)
    release_id = _identifier(public_payload.get("release_id"), "release ID")
    if output_dir.exists():
        _require(output_dir.is_dir() and not output_dir.is_symlink(), "output directory is unsafe")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
    target = output_dir / f"{release_id}.json"
    rendered = json.dumps(public_payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    encoded = rendered.encode("utf-8")
    if target.exists() or target.is_symlink():
        _require(target.is_file() and not target.is_symlink(), "output target is unsafe")
        _require(target.read_bytes() == encoded, "immutable output already differs")
        return target
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{release_id}.", suffix=".tmp", dir=output_dir
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            _require(target.is_file() and not target.is_symlink(), "output target is unsafe")
            _require(target.read_bytes() == encoded, "immutable output already differs")
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--deployment-sha", required=True)
    parser.add_argument("--generated-at")
    parser.add_argument("--public-demo-expires-at", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("evidence/releases"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generated_at = args.generated_at or datetime.now(UTC).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    try:
        payload = assemble(
            args.evidence_root,
            args.source_sha,
            args.deployment_sha,
            generated_at=generated_at,
            public_demo_expires_at=args.public_demo_expires_at,
        )
        target = write_immutable(payload, args.output_dir)
    except (OSError, ReleaseEvidenceError) as error:
        raise SystemExit(f"release evidence rejected: {error}") from error
    print(target.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
