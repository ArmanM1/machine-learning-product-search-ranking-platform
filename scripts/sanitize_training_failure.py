#!/usr/bin/env python3
"""Reduce a private SageMaker failure description to an identifier-free diagnostic."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_PHASES = {
    "argument_validation",
    "artifact_write",
    "data_load",
    "device_preflight",
    "epoch",
    "mining",
    "post_train",
    "preflight",
    "sampling",
    "subprocess_start",
    "trainer_init",
    "training_subprocess",
}
_PHASE_PATTERN = re.compile(r"\bphase[=:]\s*([a-z_]+)\b", re.IGNORECASE)
_ERROR_TYPE_PATTERN = re.compile(r"\berror_type[=:]\s*([A-Za-z][A-Za-z0-9_]{0,63})\b")
_ERROR_TYPES = {
    "contract_violation",
    "dependency_failure",
    "FileNotFoundError",
    "IsADirectoryError",
    "io_failure",
    "NotADirectoryError",
    "OSError",
    "PermissionError",
    "permission_denied",
    "resource_exhausted",
    "runtime_failure",
    "unexpected_failure",
    "ValueError",
}
_EXIT_CODE_PATTERN = re.compile(
    r"\bexit[_ ]?code(?:[=:]|\s)\s*(-?[0-9]{1,3})\b",
    re.IGNORECASE,
)
_CHECKPOINT_KEY_PATTERN = re.compile(r"/checkpoints/epoch-([0-9]{4})/COMPLETE$")
_FAILURE_SUMMARY_MEMBER_PATTERN = re.compile(
    r"^(?:\./)?artifacts/runs/train-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}/summary\.json$"
)
_MAX_MODEL_ARCHIVE_BYTES = 1024 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 100_000
_MAX_FAILURE_SUMMARY_BYTES = 1024 * 1024
_APPLICATION_FAILURE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "cuda_out_of_memory",
        ("cuda out of memory", "cuda error: out of memory", "outofmemoryerror"),
    ),
    (
        "cuda_unavailable",
        (
            "cuda training was requested but cuda is unavailable",
            "cuda device selection has no available cuda device",
        ),
    ),
    (
        "cuda_determinism",
        ("cublas_workspace_config", "does not have a deterministic implementation"),
    ),
    (
        "device_mismatch",
        (
            "actual training accelerator differs from the frozen cloud request",
            "expected all tensors to be on the same device",
        ),
    ),
    (
        "dataset_contract",
        (
            "frozen experiment references a different dataset manifest",
            "training sample missing columns",
            "candidate training accepts training rows only",
            "checkpoint selection accepts validation rows only",
            "validation frame missing columns",
            "training and validation query ids overlap",
        ),
    ),
    (
        "hard_example_sampling",
        (
            "hard fraction requested but no hard examples are available",
            "hard examples missing columns",
            "missing cross-encoder text column",
            "mixed sampler accepts training rows only",
        ),
    ),
    (
        "checkpoint_resume",
        (
            "managed-spot checkpoint",
            "checkpoint commit marker",
            "checkpoint manifest",
            "checkpoint file inventory",
        ),
    ),
    (
        "validation_metric",
        ("validation set has no query with positive ideal dcg",),
    ),
    (
        "storage_io",
        (
            "no space left on device",
            "disk quota exceeded",
            "permission denied",
            "read-only file system",
        ),
    ),
    (
        "trainer_initialization",
        (
            "cross-encoder has no underlying transformer model",
            "effective batch size must be divisible by gradient accumulation steps",
            "unsupported training device type",
        ),
    ),
    (
        "post_training_verification",
        (
            "training completed without a valid checkpoint",
            "candidate training did not change any parameters",
            "fresh checkpoint load changed the probe prediction",
        ),
    ),
)
_APPLICATION_FAILURE_SIGNAL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gpu", ("cuda", "cudnn", "cublas", "nvidia", "gpu")),
    ("memory", ("memory", "allocate", "allocation")),
    (
        "precision",
        ("float16", "fp16", "bfloat16", "bf16", "half", "autocast", "dtype"),
    ),
    ("tensor", ("tensor", "shape", "dimension", "size mismatch", "scalar type")),
    ("determinism", ("deterministic", "cublas", "cudnn")),
    ("model", ("model", "transformer", "tokenizer", "huggingface")),
    ("tabular", ("dataframe", "pandas", "column", "index", "merge", "parquet", "arrow")),
    ("sampling", ("sample", "hard example", "baseline ranking")),
    ("validation", ("validation", "ndcg", "metric")),
    ("checkpoint", ("checkpoint", "resume", "optimizer state")),
    ("filesystem", ("file", "directory", "path", "permission", "disk")),
    ("network", ("download", "connection", "network", "http", "timeout")),
    ("serialization", ("convert", "serialize", "pickle", "json", "parquet", "arrow")),
    ("contract", ("expected", "required", "missing", "invalid", "unsupported")),
    ("training", ("gradient", "backward", "loss", "optimizer", "scheduler", "epoch")),
)
_SECONDARY_STATUSES = {
    "Starting",
    "LaunchingMLInstances",
    "PreparingTrainingStack",
    "Downloading",
    "DownloadingTrainingImage",
    "Training",
    "Interrupted",
    "Restarting",
    "Uploading",
    "Stopping",
    "Stopped",
    "MaxRuntimeExceeded",
    "MaxWaitTimeExceeded",
    "Completed",
    "Failed",
    "Updating",
    "Pending",
}


class TrainingFailureDiagnosticError(ValueError):
    """A private description cannot be reduced safely."""


def _application_failure_details(failure: str) -> tuple[str, list[str]]:
    normalized = failure.casefold()
    category = next(
        (
            candidate
            for candidate, patterns in _APPLICATION_FAILURE_PATTERNS
            if any(pattern in normalized for pattern in patterns)
        ),
        "unknown",
    )
    signals = [
        signal
        for signal, patterns in _APPLICATION_FAILURE_SIGNAL_PATTERNS
        if any(pattern in normalized for pattern in patterns)
    ]
    return category, signals


def _details_from_model_archive(path: Path) -> tuple[str, list[str]]:
    try:
        archive_size = path.stat().st_size
    except OSError as error:
        raise TrainingFailureDiagnosticError("model-archive") from error
    if not 0 < archive_size <= _MAX_MODEL_ARCHIVE_BYTES:
        raise TrainingFailureDiagnosticError("model-archive-size")
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            matches: list[tarfile.TarInfo] = []
            for index, member in enumerate(archive, start=1):
                if index > _MAX_ARCHIVE_MEMBERS:
                    raise TrainingFailureDiagnosticError("model-archive-members")
                if _FAILURE_SUMMARY_MEMBER_PATTERN.fullmatch(member.name):
                    matches.append(member)
            if len(matches) != 1:
                raise TrainingFailureDiagnosticError("failure-summary-count")
            member = matches[0]
            if not member.isfile() or not 0 < member.size <= _MAX_FAILURE_SUMMARY_BYTES:
                raise TrainingFailureDiagnosticError("failure-summary-member")
            handle = archive.extractfile(member)
            if handle is None:
                raise TrainingFailureDiagnosticError("failure-summary-member")
            raw_summary = handle.read(_MAX_FAILURE_SUMMARY_BYTES + 1)
    except (OSError, tarfile.TarError) as error:
        raise TrainingFailureDiagnosticError("model-archive") from error
    if len(raw_summary) > _MAX_FAILURE_SUMMARY_BYTES:
        raise TrainingFailureDiagnosticError("failure-summary-size")
    try:
        summary = json.loads(raw_summary)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrainingFailureDiagnosticError("failure-summary-json") from error
    if not isinstance(summary, dict):
        raise TrainingFailureDiagnosticError("failure-summary-document")
    if summary.get("command") != "train" or summary.get("status") != "failed":
        raise TrainingFailureDiagnosticError("failure-summary-identity")
    failure = summary.get("failure")
    if not isinstance(failure, str) or not failure or len(failure) > 8192:
        raise TrainingFailureDiagnosticError("failure-summary-reason")
    return _application_failure_details(failure)


def _optional_nonnegative_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrainingFailureDiagnosticError(field)
    return value


def _failure_class(
    reason: str,
    exit_code: int | None,
    status: str,
    secondary_statuses: list[str],
) -> str:
    normalized = reason.casefold()
    if "MaxWaitTimeExceeded" in secondary_statuses or (
        "maxwaittime" in normalized or "max wait time" in normalized
    ):
        return "spot_wait_limit"
    if "MaxRuntimeExceeded" in secondary_statuses or (
        "maxruntime" in normalized or "max runtime" in normalized
    ):
        return "runtime_limit"
    if "cuda out of memory" in normalized or "outofmemoryerror" in normalized:
        return "out_of_memory"
    if "no space left" in normalized or "disk quota exceeded" in normalized:
        return "storage_exhausted"
    if exit_code == 137:
        return "process_killed"
    if "capacityerror" in normalized or "insufficientinstancecapacity" in normalized:
        return "capacity_error"
    if "algorithmerror" in normalized or "executeuserscripterror" in normalized:
        return "algorithm_error"
    if "clienterror" in normalized:
        return "client_error"
    if "internalservererror" in normalized or "serviceerror" in normalized:
        return "service_error"
    if status == "Stopped":
        return "stopped"
    return "unknown"


def _secondary_statuses(description: dict[str, Any]) -> list[str]:
    transitions = description.get("SecondaryStatusTransitions")
    if transitions is None:
        return []
    if not isinstance(transitions, list):
        raise TrainingFailureDiagnosticError("secondary-status-transitions")
    statuses: list[str] = []
    for transition in transitions:
        if not isinstance(transition, dict):
            raise TrainingFailureDiagnosticError("secondary-status-transition")
        status = transition.get("Status")
        if not isinstance(status, str) or status not in _SECONDARY_STATUSES:
            raise TrainingFailureDiagnosticError("secondary-status")
        statuses.append(status)
    return statuses


def _checkpoint_prefix(
    description: dict[str, Any],
    expected_job_name: str,
    expected_checkpoint_uri: str,
) -> str:
    if description.get("TrainingJobName") != expected_job_name:
        raise TrainingFailureDiagnosticError("job-identity")
    checkpoint = description.get("CheckpointConfig")
    if not isinstance(checkpoint, dict) or checkpoint.get("S3Uri") != expected_checkpoint_uri:
        raise TrainingFailureDiagnosticError("checkpoint-identity")
    parsed = urlsplit(expected_checkpoint_uri)
    if (
        parsed.scheme != "s3"
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/runs/")
        or not parsed.path.endswith("/checkpoints/")
    ):
        raise TrainingFailureDiagnosticError("checkpoint-uri")
    return parsed.path.removeprefix("/")


def _checkpoint_epochs(listing: dict[str, Any] | None, expected_prefix: str | None) -> list[int]:
    if listing is None:
        return []
    if expected_prefix is None:
        raise TrainingFailureDiagnosticError("checkpoint-prefix")
    if listing.get("IsTruncated") is not False:
        raise TrainingFailureDiagnosticError("checkpoint-listing-truncated")
    contents = listing.get("Contents", [])
    if not isinstance(contents, list):
        raise TrainingFailureDiagnosticError("checkpoint-listing")
    epochs: set[int] = set()
    for item in contents:
        if not isinstance(item, dict) or not isinstance(item.get("Key"), str):
            raise TrainingFailureDiagnosticError("checkpoint-object")
        key = item["Key"]
        if not key.startswith(expected_prefix):
            raise TrainingFailureDiagnosticError("checkpoint-object-prefix")
        match = _CHECKPOINT_KEY_PATTERN.search(key)
        if match:
            epochs.add(int(match.group(1)))
    return sorted(epochs)


def sanitize_training_failure(
    description: dict[str, Any],
    checkpoint_listing: dict[str, Any] | None = None,
    *,
    expected_job_name: str | None = None,
    expected_checkpoint_uri: str | None = None,
    application_failure_category: str | None = None,
    application_failure_signals: list[str] | None = None,
) -> dict[str, Any]:
    """Return only allowlisted diagnostic facts; never copy the private reason."""

    status = description.get("TrainingJobStatus")
    if status not in {"Failed", "Stopped"}:
        raise TrainingFailureDiagnosticError("status")
    raw_reason = description.get("FailureReason")
    if raw_reason is None:
        reason = ""
    elif isinstance(raw_reason, str):
        reason = raw_reason
    else:
        raise TrainingFailureDiagnosticError("failure-reason")
    if status == "Failed" and not reason.strip():
        raise TrainingFailureDiagnosticError("failure-reason")
    managed_spot = description.get("EnableManagedSpotTraining")
    if not isinstance(managed_spot, bool):
        raise TrainingFailureDiagnosticError("managed-spot")
    training_seconds = _optional_nonnegative_int(
        description.get("TrainingTimeInSeconds"), "training-seconds"
    )
    billable_seconds = _optional_nonnegative_int(
        description.get("BillableTimeInSeconds"), "billable-seconds"
    )
    if (
        training_seconds is not None
        and billable_seconds is not None
        and billable_seconds > training_seconds
    ):
        raise TrainingFailureDiagnosticError("billable-seconds")
    secondary_statuses = _secondary_statuses(description)
    expected_prefix: str | None = None
    if checkpoint_listing is not None:
        if not expected_job_name or not expected_checkpoint_uri:
            raise TrainingFailureDiagnosticError("checkpoint-identity")
        expected_prefix = _checkpoint_prefix(
            description, expected_job_name, expected_checkpoint_uri
        )
    completed_checkpoint_epochs = _checkpoint_epochs(checkpoint_listing, expected_prefix)
    allowed_application_categories = {
        category for category, _patterns in _APPLICATION_FAILURE_PATTERNS
    } | {"unknown"}
    if (
        application_failure_category is not None
        and application_failure_category not in allowed_application_categories
    ):
        raise TrainingFailureDiagnosticError("application-failure-category")
    failure_signals = application_failure_signals or []
    allowed_failure_signals = [signal for signal, _patterns in _APPLICATION_FAILURE_SIGNAL_PATTERNS]
    if (
        len(failure_signals) != len(set(failure_signals))
        or any(signal not in allowed_failure_signals for signal in failure_signals)
        or failure_signals
        != [signal for signal in allowed_failure_signals if signal in failure_signals]
        or (application_failure_category is None and failure_signals)
    ):
        raise TrainingFailureDiagnosticError("application-failure-signals")

    phase_match = _PHASE_PATTERN.search(reason)
    phase = phase_match.group(1).casefold() if phase_match else None
    if phase not in _PHASES:
        phase = None
    error_type_match = _ERROR_TYPE_PATTERN.search(reason)
    if error_type_match is None:
        error_type = None
    else:
        candidate_error_type = error_type_match.group(1)
        error_type = candidate_error_type if candidate_error_type in _ERROR_TYPES else "other"
    exit_code_match = _EXIT_CODE_PATTERN.search(reason)
    exit_code = int(exit_code_match.group(1)) if exit_code_match else None
    if exit_code is not None and not -255 <= exit_code <= 255:
        exit_code = None

    signals: list[str] = []
    if "Interrupted" in secondary_statuses:
        signals.append("managed_spot_interruption_observed")
        interrupted_index = secondary_statuses.index("Interrupted")
        if "Training" in secondary_statuses[interrupted_index + 1 :]:
            signals.append("managed_spot_resume_observed")
    if exit_code is not None:
        signals.append("container_exit_code_present")
    if phase is not None:
        signals.append("container_phase_present")
    if application_failure_category is not None:
        signals.append("application_failure_summary_present")

    return {
        "schema_version": "1.0.0",
        "artifact_type": "training_failure_diagnostic",
        "status": status,
        "failure_class": _failure_class(reason, exit_code, status, secondary_statuses),
        "container_phase": phase,
        "error_type": error_type,
        "application_failure_category": application_failure_category,
        "application_failure_signals": failure_signals,
        "exit_code": exit_code,
        "managed_spot": managed_spot,
        "training_seconds": training_seconds,
        "billable_seconds": billable_seconds,
        "training_minus_billable_seconds": (
            training_seconds - billable_seconds
            if training_seconds is not None and billable_seconds is not None
            else None
        ),
        "secondary_statuses": secondary_statuses,
        "completed_checkpoint_epochs": completed_checkpoint_epochs,
        "completed_checkpoint_count": len(completed_checkpoint_epochs),
        "signals": signals,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--description", type=Path, required=True)
    parser.add_argument("--checkpoint-listing", type=Path)
    parser.add_argument("--expected-job-name")
    parser.add_argument("--expected-checkpoint-uri")
    parser.add_argument("--model-archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.description.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TrainingFailureDiagnosticError("document")
        checkpoint_listing: dict[str, Any] | None = None
        if args.checkpoint_listing is not None:
            candidate = json.loads(args.checkpoint_listing.read_text(encoding="utf-8"))
            if not isinstance(candidate, dict):
                raise TrainingFailureDiagnosticError("checkpoint-listing")
            checkpoint_listing = candidate
        application_failure_category: str | None = None
        application_failure_signals: list[str] | None = None
        if args.model_archive is not None:
            application_failure_category, application_failure_signals = _details_from_model_archive(
                args.model_archive
            )
        diagnostic = sanitize_training_failure(
            payload,
            checkpoint_listing,
            expected_job_name=args.expected_job_name,
            expected_checkpoint_uri=args.expected_checkpoint_uri,
            application_failure_category=application_failure_category,
            application_failure_signals=application_failure_signals,
        )
        args.output.write_text(
            json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, TrainingFailureDiagnosticError):
        raise SystemExit("training failure description rejected") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
