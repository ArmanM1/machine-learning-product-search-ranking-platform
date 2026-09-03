"""Validate and cross-bind every durable public-serving benchmark artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from search_rank.schemas.api import PublicEvidenceEnvelope
from search_rank.schemas.evidence import BundleChecksums, ReleaseManifest
from search_rank.schemas.performance import ColdStartEvidence
from search_rank.schemas.release import PromotionPointer
from search_rank.schemas.workflow import (
    BenchmarkCostPreflight,
    BenchmarkLambdaConfiguration,
    DeploymentEvidence,
    PerformanceReport,
    PerformanceValidation,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
_DURABLE_FILES = {
    "controlled-cold-start.json",
    "cost-preflight.json",
    "lambda-configuration.json",
    "performance-report.json",
    "validation.json",
}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _json_model(path: Path, model: type[ModelT]) -> ModelT:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _head_identity(path: Path) -> tuple[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"S3 object head is not an object: {path}")
    version = payload.get("VersionId")
    etag = payload.get("ETag")
    if not isinstance(version, str) or not version:
        raise ValueError(f"S3 object head has no immutable VersionId: {path}")
    if not isinstance(etag, str) or not etag:
        raise ValueError(f"S3 object head has no ETag: {path}")
    return version, etag


def _validate_local_inventory(root: Path, inventory: BundleChecksums) -> None:
    if set(inventory.files) != _DURABLE_FILES:
        raise ValueError("benchmark checksum inventory is not the exact durable file set")
    for name, expected in inventory.files.items():
        path = root / name
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"benchmark checksum differs for {name}")


def _validate_published_inventory(
    path: Path,
    *,
    prefix: str,
    release_id: str,
    benchmark_run_id: str,
    inventory_path: Path,
) -> None:
    digest = _sha256(inventory_path).removeprefix("sha256:")
    expected_prefix = f"public/{release_id}/performance/runs/{benchmark_run_id}/sha256-{digest}/"
    if prefix != expected_prefix:
        raise ValueError("benchmark publication prefix is not run- and content-addressed")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("IsTruncated") is True:
        raise ValueError("published benchmark object listing is invalid or truncated")
    contents = payload.get("Contents", [])
    if not isinstance(contents, list):
        raise ValueError("published benchmark object listing has no contents array")
    observed = {
        item.get("Key")
        for item in contents
        if isinstance(item, dict) and isinstance(item.get("Key"), str)
    }
    expected = {prefix + name for name in _DURABLE_FILES | {"evidence-checksums.json"}}
    if observed != expected:
        raise ValueError("published benchmark object inventory is not exact")


def validate(args: argparse.Namespace) -> None:
    root = args.evidence_dir
    cost = _json_model(root / "cost-preflight.json", BenchmarkCostPreflight)
    lambda_config = _json_model(root / "lambda-configuration.json", BenchmarkLambdaConfiguration)
    cold = _json_model(root / "controlled-cold-start.json", ColdStartEvidence)
    report = _json_model(root / "performance-report.json", PerformanceReport)
    validation = _json_model(root / "validation.json", PerformanceValidation)
    inventory_path = root / "evidence-checksums.json"
    inventory = _json_model(inventory_path, BundleChecksums)
    _validate_local_inventory(root, inventory)

    pointer = _json_model(args.promotion_pointer, PromotionPointer)
    release = _json_model(args.release_manifest, ReleaseManifest)
    release_inventory = _json_model(args.release_checksums, BundleChecksums)
    public = _json_model(args.public_evidence, PublicEvidenceEnvelope)
    deployment = _json_model(args.deployment_evidence, DeploymentEvidence)
    pointer_version, pointer_etag = _head_identity(args.promotion_pointer_head)
    deployment_version, deployment_etag = _head_identity(args.deployment_evidence_head)

    ids = report.identifiers
    binding = report.release_binding
    expected_identity = (
        args.benchmark_run_id,
        args.release_id,
        args.model_id,
        args.region,
        args.public_origin,
    )
    if (
        (
            cost.benchmark_run_id,
            cost.release_id,
            cost.model_id,
            cost.region,
            cost.public_origin,
        )
        != expected_identity
        or (
            lambda_config.benchmark_run_id,
            lambda_config.release_id,
            lambda_config.model_id,
            lambda_config.region,
        )
        != expected_identity[:4]
        or (
            ids.benchmark_run_id,
            ids.release_id,
            ids.model_id,
            ids.region,
            ids.public_origin,
        )
        != expected_identity
        or (
            validation.benchmark_run_id,
            validation.release_id,
            validation.model_id,
        )
        != expected_identity[:3]
    ):
        raise ValueError("benchmark durable artifacts do not share the expected run identity")
    if ids.benchmark_harness_git_sha != args.benchmark_harness_git_sha:
        raise ValueError("benchmark report differs from the executing harness commit")
    if ids.public_run_id != args.public_run_id or ids.evidence_mode != args.evidence_mode:
        raise ValueError("benchmark report differs from the selected public evidence run")
    if ids.dataset_manifest_hash != args.dataset_manifest_hash:
        raise ValueError("benchmark report differs from the selected dataset identity")
    if ids.model_artifact_checksum != args.model_artifact_checksum:
        raise ValueError("benchmark report differs from the selected model artifact")
    if lambda_config.function_name != args.function_name:
        raise ValueError("benchmark Lambda configuration names a different function")
    if report.lambda_configuration != lambda_config:
        raise ValueError("performance report embeds different Lambda configuration evidence")
    if report.controlled_cold_start != cold or deployment.controlled_cold_start != cold:
        raise ValueError("cold-start evidence differs across deployment and benchmark artifacts")
    if validation.performance_report_sha256 != _sha256(root / "performance-report.json"):
        raise ValueError("performance validation does not checksum-bind the report")
    if validation.evidence_file_count != len(_DURABLE_FILES):
        raise ValueError("performance validation records the wrong durable file count")
    primary = next(
        condition
        for condition in report.conditions
        if condition.candidate_count == report.protocol.primary_latency_candidate_count
        and condition.offered_concurrency == report.protocol.primary_latency_offered_concurrency
    )
    secondary = [condition for condition in report.conditions if condition is not primary]
    if (
        validation.minimum_warmup_condition_success_count
        != min(condition.warmup.success_count for condition in report.conditions)
        or validation.primary_latency_condition_success_count != primary.measured.success_count
        or validation.minimum_secondary_condition_success_count
        != min(condition.measured.success_count for condition in secondary)
    ):
        raise ValueError("performance validation success floors differ from the report")
    if not (
        cost.checked_at <= report.started_at
        and lambda_config.checked_at <= report.started_at
        and cold.measured_at <= report.started_at
        and report.completed_at <= validation.validated_at
    ):
        raise ValueError("benchmark evidence timestamps are not causally ordered")

    promoted = [model for model in release.models if model.model_id == args.model_id]
    public_run = public.run
    if len(promoted) != 1:
        raise ValueError("selected model is absent or duplicated in the release manifest")
    if not (
        pointer.release_id == release.release_id == deployment.release_id == args.release_id
        and pointer.model_id == release.promoted_model_id == deployment.model_id == args.model_id
        and pointer.bundle_s3_key == binding.bundle_s3_key
        and pointer.evidence_mode
        == release.evidence_mode
        == public.evidence_mode
        == args.evidence_mode
        and pointer.evaluation_report_id == release.evaluation_report_id
        and pointer.git_sha == release.git_sha == public_run.git_sha == ids.release_git_sha
        and release.dataset_manifest_hash
        == public_run.dataset_manifest_hash
        == ids.dataset_manifest_hash
        and release.split_manifest_hash == public_run.split_manifest_hash
        and public_run.run_id == ids.public_run_id
        and promoted[0].artifact_checksum
        == public_run.model_artifact_checksum
        == ids.model_artifact_checksum
        and deployment.production_lambda_version == lambda_config.function_version
        and deployment.promoted_pointer_version_id == pointer_version
        and deployment.production_api_smoke.base_url_origin == args.public_origin
    ):
        raise ValueError("release, deployment, model, and benchmark identities are inconsistent")

    release_hash = _sha256(args.release_manifest)
    public_hash = _sha256(args.public_evidence)
    release_inventory_hash = _sha256(args.release_checksums)
    deployment_hash = _sha256(args.deployment_evidence)
    if not (
        release_inventory.files.get("release-manifest.json") == release_hash
        and release_inventory.files.get("public-evidence.json") == public_hash
        and binding.release_manifest_sha256 == release_hash
        and binding.public_evidence_sha256 == public_hash
        and binding.bundle_checksums_sha256 == release_inventory_hash
        and binding.deployment_evidence_sha256 == deployment_hash
        and binding.promotion_pointer_version_id == pointer_version
        and binding.promotion_pointer_etag == pointer_etag
        and binding.deployment_evidence_version_id == deployment_version
        and binding.deployment_evidence_etag == deployment_etag
    ):
        raise ValueError("benchmark source checksums or immutable S3 versions are inconsistent")

    if args.publication_prefix is not None:
        digest = _sha256(inventory_path).removeprefix("sha256:")
        expected_prefix = (
            f"public/{args.release_id}/performance/runs/{args.benchmark_run_id}/sha256-{digest}/"
        )
        if args.publication_prefix != expected_prefix:
            raise ValueError("benchmark publication prefix is not run- and content-addressed")
    if args.published_objects is not None:
        if args.publication_prefix is None:
            raise ValueError("published object list requires the exact publication prefix")
        _validate_published_inventory(
            args.published_objects,
            prefix=args.publication_prefix,
            release_id=args.release_id,
            benchmark_run_id=args.benchmark_run_id,
            inventory_path=inventory_path,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--promotion-pointer", type=Path, required=True)
    parser.add_argument("--promotion-pointer-head", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--release-checksums", type=Path, required=True)
    parser.add_argument("--public-evidence", type=Path, required=True)
    parser.add_argument("--deployment-evidence", type=Path, required=True)
    parser.add_argument("--deployment-evidence-head", type=Path, required=True)
    parser.add_argument("--benchmark-run-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--public-run-id", required=True)
    parser.add_argument("--evidence-mode", choices=("validation_only", "verified"), required=True)
    parser.add_argument("--dataset-manifest-hash", required=True)
    parser.add_argument("--model-artifact-checksum", required=True)
    parser.add_argument("--benchmark-harness-git-sha", required=True)
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--published-objects", type=Path)
    parser.add_argument("--publication-prefix")
    return parser


def main() -> None:
    validate(_parser().parse_args())


if __name__ == "__main__":
    main()
