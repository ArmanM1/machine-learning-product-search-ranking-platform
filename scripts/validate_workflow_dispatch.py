"""Validate compact GitHub workflow-dispatch JSON before exporting any values."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

WorkflowName = Literal["train", "release", "bootstrap-baseline"]

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,99}$")
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,62}$")
SAFE_REPOSITORY_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
DATA_PREFIX = re.compile(r"^data/processed/[A-Za-z0-9][A-Za-z0-9._/-]*$")
DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")
S3_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
ECR_REPOSITORY = re.compile(
    r"^[0-9]{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/"
    r"[a-z0-9]+(?:[._/-][a-z0-9]+)*$"
)

TRAIN_ENV = {
    "experiment_config_path": "CONFIG_PATH",
    "dataset_manifest_hash": "DATASET_MANIFEST_HASH",
    "prepared_data_s3_prefix": "PREPARED_DATA_S3_PREFIX",
    "training_image_digest": "TRAINING_IMAGE_DIGEST",
    "run_kind": "RUN_KIND",
    "instance_type": "INSTANCE_TYPE",
    "accelerator": "ACCELERATOR",
    "maximum_timeout_seconds": "MAX_TIMEOUT_SECONDS",
    "declared_job_cost_cap_usd": "DECLARED_JOB_COST_CAP_USD",
    "estimated_remaining_non_job_usd": "ESTIMATED_REMAINING_NON_JOB_USD",
    "gpu_hours_used_to_date": "GPU_HOURS_USED_TO_DATE",
    "cpu_hours_used_to_date": "CPU_HOURS_USED_TO_DATE",
}

RELEASE_ENV = {
    "candidate_run_id": "CANDIDATE_RUN_ID",
    "candidate_model_id": "CANDIDATE_MODEL_ID",
    "candidate_artifact_s3_key": "CANDIDATE_ARTIFACT_S3_KEY",
    "candidate_artifact_sha256": "CANDIDATE_ARTIFACT_SHA256",
    "candidate_checkpoint_sha256": "CANDIDATE_CHECKPOINT_SHA256",
    "candidate_training_config_sha256": "CANDIDATE_CONFIG_SHA256",
    "candidate_training_config_path": "CANDIDATE_CONFIG_PATH",
    "trial_selection_s3_key": "TRIAL_SELECTION_S3_KEY",
    "trial_selection_sha256": "TRIAL_SELECTION_SHA256",
    "frozen_evaluation_config_path": "FROZEN_CONFIG_PATH",
    "frozen_evaluation_config_sha256": "FROZEN_CONFIG_SHA256",
    "dataset_manifest_hash": "DATASET_MANIFEST_HASH",
    "heldout_data_s3_prefix": "HELDOUT_DATA_S3_PREFIX",
    "baseline_ids": "BASELINE_IDS",
    "strongest_baseline_id": "STRONGEST_BASELINE_ID",
    "baseline_run_summary_s3_key": "BASELINE_RUN_SUMMARY_S3_KEY",
    "baseline_run_summary_sha256": "BASELINE_RUN_SUMMARY_SHA256",
    "baseline_selection_s3_key": "BASELINE_SELECTION_S3_KEY",
    "baseline_selection_sha256": "BASELINE_SELECTION_SHA256",
    "baseline_config_path": "BASELINE_CONFIG_PATH",
    "baseline_config_file_sha256": "BASELINE_CONFIG_FILE_SHA256",
    "evaluation_image_digest": "EVALUATION_IMAGE_DIGEST",
    "test_access_counter": "TEST_ACCESS_COUNTER",
    "maximum_timeout_seconds": "MAX_TIMEOUT_SECONDS",
    "declared_job_cost_cap_usd": "DECLARED_JOB_COST_CAP_USD",
    "estimated_remaining_non_job_usd": "ESTIMATED_REMAINING_NON_JOB_USD",
    "cpu_hours_used_to_date": "CPU_HOURS_USED_TO_DATE",
}

BOOTSTRAP_BASELINE_ENV = {
    "baseline_command_summary_s3_key": "BASELINE_COMMAND_SUMMARY_S3_KEY",
    "baseline_command_summary_sha256": "BASELINE_COMMAND_SUMMARY_SHA256",
    "baseline_summary_s3_key": "BASELINE_SUMMARY_S3_KEY",
    "baseline_summary_sha256": "BASELINE_SUMMARY_SHA256",
    "dataset_manifest_s3_key": "DATASET_MANIFEST_S3_KEY",
    "dataset_manifest_sha256": "DATASET_MANIFEST_SHA256",
    "dataset_processed_sha256": "DATASET_PROCESSED_SHA256",
    "curated_queries_s3_key": "CURATED_QUERIES_S3_KEY",
    "curated_queries_sha256": "CURATED_QUERIES_SHA256",
    "baseline_config_path": "BASELINE_CONFIG_PATH",
    "baseline_config_file_sha256": "BASELINE_CONFIG_FILE_SHA256",
    "strongest_baseline_id": "STRONGEST_BASELINE_ID",
    "evidence_image_digest": "EVIDENCE_IMAGE_DIGEST",
    "hardware_class": "HARDWARE_CLASS",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"dispatch config contains duplicate key: {key}")
        result[key] = value
    return result


def _load_exact_object(raw: str, expected_keys: set[str]) -> dict[str, str]:
    if not raw or len(raw.encode("utf-8")) > 32_768:
        raise ValueError(
            "dispatch config must be a non-empty JSON object no larger than 32768 bytes"
        )
    try:
        decoded = json.loads(raw, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as error:
        raise ValueError("dispatch config is not valid JSON") from error
    if type(decoded) is not dict:
        raise ValueError("dispatch config must be one JSON object")
    observed_keys = set(decoded)
    if observed_keys != expected_keys:
        missing = sorted(expected_keys - observed_keys)
        extra = sorted(observed_keys - expected_keys)
        raise ValueError(f"dispatch config keys are not exact; missing={missing}, extra={extra}")
    values: dict[str, str] = {}
    for key, value in decoded.items():
        if type(value) is not str:
            raise ValueError(f"dispatch config field {key} must be a JSON string")
        if not value or len(value) > 2048 or any(ord(character) < 32 for character in value):
            raise ValueError(
                f"dispatch config field {key} is empty, oversized, or contains controls"
            )
        values[key] = value
    return values


def _require_pattern(values: Mapping[str, str], key: str, pattern: re.Pattern[str]) -> None:
    if pattern.fullmatch(values[key]) is None:
        raise ValueError(f"dispatch config field {key} has an invalid format")


def _require_safe_path(values: Mapping[str, str], key: str, pattern: re.Pattern[str]) -> None:
    _require_pattern(values, key, pattern)
    if ".." in values[key] or "//" in values[key]:
        raise ValueError(f"dispatch config field {key} is not a normalized path")


def _require_choice(values: Mapping[str, str], key: str, choices: set[str]) -> None:
    if values[key] not in choices:
        raise ValueError(f"dispatch config field {key} is outside its allowlist")


def _require_non_negative_decimal(values: Mapping[str, str], key: str) -> None:
    _require_pattern(values, key, DECIMAL)
    try:
        number = Decimal(values[key])
    except InvalidOperation as error:
        raise ValueError(f"dispatch config field {key} is not decimal") from error
    if not number.is_finite() or number < 0:
        raise ValueError(f"dispatch config field {key} must be finite and non-negative")


def _external(environment: Mapping[str, str], name: str, pattern: re.Pattern[str]) -> str:
    value = environment.get(name, "")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"required workflow environment {name} is missing or invalid")
    return value


def _canonical_checksum(values: Mapping[str, str]) -> str:
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _validate_train(values: dict[str, str], environment: Mapping[str, str]) -> dict[str, str]:
    config_kinds = {
        "configs/experiments/candidate-v1.yaml": {"development", "final"},
        "configs/experiments/candidate-random-ablation-v1.yaml": {"ablation"},
        "configs/experiments/candidate-title-ablation-v1.yaml": {"ablation"},
    }
    _require_choice(values, "experiment_config_path", set(config_kinds))
    _require_choice(values, "run_kind", config_kinds[values["experiment_config_path"]])
    _require_pattern(values, "dataset_manifest_hash", SHA256)
    _require_safe_path(values, "prepared_data_s3_prefix", DATA_PREFIX)
    _require_pattern(values, "training_image_digest", SHA256)
    _require_choice(values, "instance_type", {"ml.m5.xlarge", "ml.g4dn.xlarge"})
    _require_choice(values, "accelerator", {"cpu", "gpu"})
    if (values["instance_type"], values["accelerator"]) not in {
        ("ml.m5.xlarge", "cpu"),
        ("ml.g4dn.xlarge", "gpu"),
    }:
        raise ValueError("training instance_type and accelerator do not match")
    _require_pattern(values, "maximum_timeout_seconds", POSITIVE_INTEGER)
    timeout = int(values["maximum_timeout_seconds"])
    limit = 14_400 if values["accelerator"] == "gpu" and values["run_kind"] != "final" else 18_000
    if timeout > limit:
        raise ValueError("training maximum_timeout_seconds exceeds the run-kind hardware limit")
    for key in (
        "declared_job_cost_cap_usd",
        "estimated_remaining_non_job_usd",
        "gpu_hours_used_to_date",
        "cpu_hours_used_to_date",
    ):
        _require_non_negative_decimal(values, key)

    output = {environment_name: values[key] for key, environment_name in TRAIN_ENV.items()}
    bucket = _external(environment, "ARTIFACT_BUCKET", S3_BUCKET)
    repository = _external(environment, "TRAIN_REPOSITORY", ECR_REPOSITORY)
    output["PREPARED_DATA_S3_URI"] = f"s3://{bucket}/{values['prepared_data_s3_prefix']}"
    output["TRAINING_IMAGE_URI"] = f"{repository}@{values['training_image_digest']}"
    return output


def _validate_release(values: dict[str, str], environment: Mapping[str, str]) -> dict[str, str]:
    _require_pattern(values, "candidate_run_id", SAFE_RUN_ID)
    _require_pattern(values, "candidate_model_id", SAFE_ID)
    _require_safe_path(
        values,
        "candidate_artifact_s3_key",
        re.compile(r"^runs/[A-Za-z0-9._/-]+\.tar\.gz$"),
    )
    for key in (
        "candidate_artifact_sha256",
        "candidate_checkpoint_sha256",
        "trial_selection_sha256",
        "frozen_evaluation_config_sha256",
        "baseline_run_summary_sha256",
        "baseline_selection_sha256",
        "baseline_config_file_sha256",
    ):
        _require_pattern(values, key, HEX_SHA256)
    _require_pattern(values, "candidate_training_config_sha256", SHA256)
    _require_choice(
        values,
        "candidate_training_config_path",
        {"configs/experiments/candidate-v1.yaml"},
    )
    _require_safe_path(
        values,
        "trial_selection_s3_key",
        re.compile(r"^runs/trial-selection/trial-selection-[0-9a-f]{20}/trial-selection\.json$"),
    )
    _require_choice(
        values,
        "frozen_evaluation_config_path",
        {"configs/experiments/release-v1.yaml"},
    )
    _require_pattern(values, "dataset_manifest_hash", SHA256)
    _require_safe_path(values, "heldout_data_s3_prefix", DATA_PREFIX)
    _require_pattern(
        values,
        "baseline_ids",
        re.compile(r"^[A-Za-z0-9._@-]+(?:,[A-Za-z0-9._@-]+)+$"),
    )
    _require_pattern(values, "strongest_baseline_id", SAFE_ID)
    baseline_ids = values["baseline_ids"].split(",")
    if len(baseline_ids) != len(set(baseline_ids)):
        raise ValueError("release baseline_ids must be unique")
    if values["strongest_baseline_id"] not in baseline_ids:
        raise ValueError("release strongest_baseline_id is absent from baseline_ids")
    _require_safe_path(
        values,
        "baseline_run_summary_s3_key",
        re.compile(r"^runs/[A-Za-z0-9._/-]+/summary\.json$"),
    )
    _require_safe_path(
        values,
        "baseline_selection_s3_key",
        re.compile(r"^runs/[A-Za-z0-9._/-]+/baseline-summary\.json$"),
    )
    _require_choice(
        values,
        "baseline_config_path",
        {"configs/experiments/baselines-v1.yaml"},
    )
    _require_pattern(values, "evaluation_image_digest", SHA256)
    for key in ("test_access_counter", "maximum_timeout_seconds"):
        _require_pattern(values, key, POSITIVE_INTEGER)
    if int(values["maximum_timeout_seconds"]) > 7200:
        raise ValueError("release maximum_timeout_seconds exceeds two hours per clean job")
    for key in (
        "declared_job_cost_cap_usd",
        "estimated_remaining_non_job_usd",
        "cpu_hours_used_to_date",
    ):
        _require_non_negative_decimal(values, key)

    output = {environment_name: values[key] for key, environment_name in RELEASE_ENV.items()}
    bucket = _external(environment, "ARTIFACT_BUCKET", S3_BUCKET)
    repository = _external(environment, "EVAL_REPOSITORY", ECR_REPOSITORY)
    output["CANDIDATE_ARTIFACT_S3_URI"] = f"s3://{bucket}/{values['candidate_artifact_s3_key']}"
    output["HELDOUT_DATA_S3_URI"] = f"s3://{bucket}/{values['heldout_data_s3_prefix']}"
    output["BASELINE_RUN_SUMMARY_S3_URI"] = f"s3://{bucket}/{values['baseline_run_summary_s3_key']}"
    output["BASELINE_SELECTION_S3_URI"] = f"s3://{bucket}/{values['baseline_selection_s3_key']}"
    output["EVALUATION_IMAGE_URI"] = f"{repository}@{values['evaluation_image_digest']}"
    return output


def _validate_bootstrap_baseline(
    values: dict[str, str], environment: Mapping[str, str]
) -> dict[str, str]:
    del environment
    path_patterns = {
        "baseline_command_summary_s3_key": re.compile(r"^runs/[A-Za-z0-9._/-]+/summary\.json$"),
        "baseline_summary_s3_key": re.compile(r"^runs/[A-Za-z0-9._/-]+/baseline-summary\.json$"),
        "dataset_manifest_s3_key": re.compile(r"^runs/[A-Za-z0-9._/-]+/manifest\.json$"),
        "curated_queries_s3_key": re.compile(r"^runs/[A-Za-z0-9._/-]+/curated-queries\.json$"),
    }
    for key, pattern in path_patterns.items():
        _require_safe_path(values, key, pattern)
    for key in (
        "baseline_command_summary_sha256",
        "baseline_summary_sha256",
        "dataset_manifest_sha256",
        "curated_queries_sha256",
        "baseline_config_file_sha256",
    ):
        _require_pattern(values, key, HEX_SHA256)
    _require_pattern(values, "dataset_processed_sha256", SHA256)
    _require_choice(
        values,
        "baseline_config_path",
        {"configs/experiments/baselines-v1.yaml"},
    )
    _require_pattern(values, "strongest_baseline_id", SAFE_ID)
    _require_pattern(values, "evidence_image_digest", SHA256)
    _require_choice(values, "hardware_class", {"github-hosted-ubuntu-x86_64"})
    return {
        environment_name: values[key] for key, environment_name in BOOTSTRAP_BASELINE_ENV.items()
    }


VALIDATORS: dict[
    WorkflowName,
    tuple[dict[str, str], Callable[[dict[str, str], Mapping[str, str]], dict[str, str]]],
] = {
    "train": (TRAIN_ENV, _validate_train),
    "release": (RELEASE_ENV, _validate_release),
    "bootstrap-baseline": (BOOTSTRAP_BASELINE_ENV, _validate_bootstrap_baseline),
}


def validate_dispatch_config(
    workflow: WorkflowName, raw: str, environment: Mapping[str, str]
) -> dict[str, str]:
    environment_map, validator = VALIDATORS[workflow]
    values = _load_exact_object(raw, set(environment_map))
    output = validator(values, environment)
    output["DISPATCH_CONFIG_SHA256"] = _canonical_checksum(values)
    return output


def _write_github_environment(path: Path, values: Mapping[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for name, value in sorted(values.items()):
            if re.fullmatch(r"^[A-Z][A-Z0-9_]*$", name) is None or "\n" in value:
                raise ValueError("validated dispatch output is unsafe for GITHUB_ENV")
            handle.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=sorted(VALIDATORS), required=True)
    parser.add_argument("--config-env", default="DISPATCH_CONFIG_JSON")
    parser.add_argument("--github-env", type=Path, default=None)
    args = parser.parse_args(argv)
    github_environment_value = (
        str(args.github_env) if args.github_env is not None else os.environ.get("GITHUB_ENV")
    )
    if not github_environment_value:
        raise SystemExit("GITHUB_ENV is not configured")
    github_environment = Path(github_environment_value)
    raw = os.environ.get(args.config_env, "")
    try:
        values = validate_dispatch_config(args.workflow, raw, os.environ)
        _write_github_environment(github_environment, values)
    except (OSError, ValueError) as error:
        raise SystemExit(f"dispatch config rejected: {error}") from error
    print(f"Validated exact {args.workflow} dispatch config ({values['DISPATCH_CONFIG_SHA256']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
