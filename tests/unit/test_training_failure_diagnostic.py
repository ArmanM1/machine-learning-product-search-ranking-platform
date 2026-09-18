from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from botocore.session import Session

from scripts import sanitize_training_failure as sanitizer
from scripts.sanitize_training_failure import (
    TrainingFailureDiagnosticError,
    main,
    sanitize_training_failure,
)

ROOT = Path(__file__).resolve().parents[2]
TRAIN_WORKFLOW = ROOT / ".github" / "workflows" / "train.yml"
JOB_NAME = "product-search-ranking-prod-final-hsensitive"
ARTIFACT_BUCKET = "private-sensitive-bucket"
CHECKPOINT_PREFIX = f"runs/{JOB_NAME}/checkpoints/"
CHECKPOINT_URI = f"s3://{ARTIFACT_BUCKET}/{CHECKPOINT_PREFIX}"


def test_secondary_status_allowlist_matches_the_current_aws_api_model() -> None:
    service = Session().get_service_model("sagemaker")
    output = service.operation_model("DescribeTrainingJob").output_shape
    assert output is not None
    transitions = output.members["SecondaryStatusTransitions"]
    status = transitions.member.members["Status"]

    assert set(status.enum) == sanitizer._SECONDARY_STATUSES


def _description(reason: str) -> dict[str, object]:
    return {
        "TrainingJobName": JOB_NAME,
        "TrainingJobArn": "arn:aws:sagemaker:us-east-1:123456789012:training-job/sensitive",
        "TrainingJobStatus": "Failed",
        "FailureReason": reason,
        "EnableManagedSpotTraining": True,
        "TrainingTimeInSeconds": 4_931,
        "BillableTimeInSeconds": 2_501,
        "SecondaryStatusTransitions": [
            {"Status": "Starting", "StatusMessage": "sensitive startup detail"},
            {"Status": "Training", "StatusMessage": "sensitive training detail"},
            {"Status": "Failed", "StatusMessage": "sensitive failure detail"},
        ],
        "CheckpointConfig": {"S3Uri": CHECKPOINT_URI, "LocalPath": "/opt/ml/checkpoints"},
        "OutputDataConfig": {"S3OutputPath": "s3://private-sensitive-bucket/output"},
    }


@pytest.mark.parametrize(
    ("reason", "expected_class", "expected_phase", "expected_exit"),
    (
        (
            "AlgorithmError: phase=training_subprocess; exit_code=1; "
            "s3://private-sensitive-bucket user@example.com",
            "algorithm_error",
            "training_subprocess",
            1,
        ),
        ("AlgorithmError: ExecuteUserScriptError: ExitCode 137", "process_killed", None, 137),
        ("CUDA out of memory", "out_of_memory", None, None),
        ("MaxWaitTime exceeded", "spot_wait_limit", None, None),
        ("MaxRuntime exceeded", "runtime_limit", None, None),
        ("No space left on device", "storage_exhausted", None, None),
    ),
)
def test_private_failure_is_reduced_to_allowlisted_facts(
    reason: str,
    expected_class: str,
    expected_phase: str | None,
    expected_exit: int | None,
) -> None:
    diagnostic = sanitize_training_failure(_description(reason))
    encoded = json.dumps(diagnostic, sort_keys=True)

    assert diagnostic["failure_class"] == expected_class
    assert diagnostic["container_phase"] == expected_phase
    assert diagnostic["exit_code"] == expected_exit
    assert diagnostic["training_minus_billable_seconds"] == 2_430
    assert "managed_spot_interruption_observed" not in diagnostic["signals"]
    assert diagnostic["secondary_statuses"] == ["Starting", "Training", "Failed"]
    assert diagnostic["completed_checkpoint_epochs"] == []
    assert set(diagnostic) == {
        "schema_version",
        "artifact_type",
        "status",
        "failure_class",
        "container_phase",
        "error_type",
        "exit_code",
        "managed_spot",
        "training_seconds",
        "billable_seconds",
        "training_minus_billable_seconds",
        "secondary_statuses",
        "completed_checkpoint_epochs",
        "completed_checkpoint_count",
        "signals",
    }
    for private in (
        reason,
        "private-sensitive-bucket",
        "user@example.com",
        "123456789012",
        "product-search-ranking-prod-final-hsensitive",
    ):
        assert private not in encoded


@pytest.mark.parametrize(
    "mutation",
    (
        {"TrainingJobStatus": "Completed"},
        {"FailureReason": ""},
        {"EnableManagedSpotTraining": "true"},
        {"TrainingTimeInSeconds": -1},
        {"BillableTimeInSeconds": 5_000},
        {"SecondaryStatusTransitions": [{"Status": "SensitiveUnknownStatus"}]},
    ),
)
def test_malformed_or_nonfailed_description_is_rejected(mutation: dict[str, object]) -> None:
    description = _description("AlgorithmError")
    description.update(mutation)

    with pytest.raises(TrainingFailureDiagnosticError):
        sanitize_training_failure(description)


def test_early_stopped_failure_accepts_missing_timings_and_reason() -> None:
    description = _description("unused")
    description.update(
        {
            "TrainingJobStatus": "Stopped",
            "FailureReason": None,
            "SecondaryStatusTransitions": [
                {"Status": "Starting"},
                {"Status": "MaxWaitTimeExceeded"},
                {"Status": "Stopped"},
            ],
        }
    )
    description.pop("TrainingTimeInSeconds")
    description.pop("BillableTimeInSeconds")

    diagnostic = sanitize_training_failure(description)

    assert diagnostic["status"] == "Stopped"
    assert diagnostic["failure_class"] == "spot_wait_limit"
    assert diagnostic["training_seconds"] is None
    assert diagnostic["billable_seconds"] is None
    assert diagnostic["training_minus_billable_seconds"] is None


def test_unknown_error_type_is_mapped_instead_of_exported() -> None:
    private_type = "CustomerSpecificIdentifier"
    diagnostic = sanitize_training_failure(
        _description(f"AlgorithmError: error_type={private_type}; exit_code=1")
    )

    assert diagnostic["error_type"] == "other"
    assert private_type not in json.dumps(diagnostic)


def test_cli_never_echoes_private_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "private.json"
    output = tmp_path / "diagnostic.json"
    secret_reason = "AlgorithmError: phase=training_subprocess; exit_code=1; secret-token"
    source.write_text(json.dumps(_description(secret_reason)), encoding="utf-8")

    assert main(["--description", str(source), "--output", str(output)]) == 0
    assert secret_reason not in capsys.readouterr().out
    assert secret_reason not in output.read_text(encoding="utf-8")


def test_status_transitions_and_checkpoint_markers_prove_resume_progress() -> None:
    description = _description("AlgorithmError: phase=training_subprocess; exit_code=1")
    description["SecondaryStatusTransitions"] = [
        {"Status": "Starting"},
        {"Status": "Training"},
        {"Status": "Interrupted"},
        {"Status": "Training"},
        {"Status": "Failed"},
    ]
    listing = {
        "IsTruncated": False,
        "Contents": [
            {"Key": f"{CHECKPOINT_PREFIX}epoch-0001/COMPLETE"},
            {"Key": f"{CHECKPOINT_PREFIX}epoch-0001/model/model.safetensors"},
            {"Key": f"{CHECKPOINT_PREFIX}epoch-0003/COMPLETE"},
        ],
    }

    diagnostic = sanitize_training_failure(
        description,
        listing,
        expected_job_name=JOB_NAME,
        expected_checkpoint_uri=CHECKPOINT_URI,
    )
    encoded = json.dumps(diagnostic)

    assert diagnostic["completed_checkpoint_epochs"] == [1, 3]
    assert diagnostic["completed_checkpoint_count"] == 2
    assert diagnostic["signals"][:2] == [
        "managed_spot_interruption_observed",
        "managed_spot_resume_observed",
    ]
    assert "product-search-ranking-prod-final-hsensitive" not in encoded


@pytest.mark.parametrize(
    "mutation",
    (
        {"IsTruncated": True, "Contents": []},
        {"Contents": []},
        {
            "IsTruncated": False,
            "Contents": [{"Key": "runs/a-different-job/checkpoints/epoch-0001/COMPLETE"}],
        },
    ),
)
def test_checkpoint_listing_must_be_complete_and_bound(mutation: dict[str, object]) -> None:
    with pytest.raises(TrainingFailureDiagnosticError):
        sanitize_training_failure(
            _description("AlgorithmError"),
            mutation,
            expected_job_name=JOB_NAME,
            expected_checkpoint_uri=CHECKPOINT_URI,
        )


@pytest.mark.parametrize(
    ("job_name", "checkpoint_uri"),
    (("different-job", CHECKPOINT_URI), (JOB_NAME, "s3://different-bucket/checkpoints/")),
)
def test_checkpoint_request_must_match_the_described_job(
    job_name: str, checkpoint_uri: str
) -> None:
    listing = {"IsTruncated": False, "Contents": []}

    with pytest.raises(TrainingFailureDiagnosticError):
        sanitize_training_failure(
            _description("AlgorithmError"),
            listing,
            expected_job_name=job_name,
            expected_checkpoint_uri=checkpoint_uri,
        )


def test_read_only_diagnostic_job_cannot_submit_compute_or_publish_raw_reason() -> None:
    workflow = yaml.safe_load(TRAIN_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    diagnostic = jobs["diagnose-failed-job"]
    diagnostic_source = json.dumps(diagnostic, sort_keys=True)

    assert diagnostic["environment"] == "aws-training"
    assert diagnostic["timeout-minutes"] == 10
    assert diagnostic["needs"] == "validate-mode"
    assert diagnostic["env"] == {
        "TARGET_JOB_NAME": "${{ secrets.AWS_FAILED_TRAINING_JOB_NAME }}",
        "ARTIFACT_BUCKET": "${{ vars.AWS_ARTIFACT_BUCKET }}",
    }
    assert "describe-training-job" in diagnostic_source
    assert "sanitize_training_failure.py" in diagnostic_source
    assert "--no-paginate" in diagnostic_source
    assert "--expected-job-name" in diagnostic_source
    assert "--expected-checkpoint-uri" in diagnostic_source
    assert "create-training-job" not in diagnostic_source
    assert "stop-training-job" not in diagnostic_source
    assert "FailureReason" not in diagnostic_source
    assert "AWS_FAILED_TRAINING_JOB_NAME" not in jobs["submit"]["env"]
    assert "inputs.diagnostic_only == false" in jobs["submit"]["if"]
    assert "inputs.diagnostic_only == false" in jobs["quota-probe"]["if"]
    assert "inputs.diagnostic_only == true" in diagnostic["if"]

    mode_guard = jobs["validate-mode"]
    guard_source = json.dumps(mode_guard, sort_keys=True)
    assert mode_guard["timeout-minutes"] == 2
    assert mode_guard["permissions"] == {"contents": "read"}
    assert "id-token" not in mode_guard["permissions"]
    assert "QUOTA_PROBE_ONLY" in guard_source
    assert "DIAGNOSTIC_ONLY" in guard_source
    assert "mutually exclusive" in guard_source
    assert jobs["submit"]["needs"] == "validate-mode"
    assert jobs["quota-probe"]["needs"] == "validate-mode"
