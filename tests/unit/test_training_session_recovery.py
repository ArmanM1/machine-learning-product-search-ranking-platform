from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from botocore.session import Session

from scripts.validate_existing_training_job import (
    DIRECTLY_VALIDATED_CREATE_FIELDS,
    FINGERPRINT_ONLY_CREATE_FIELDS,
    REQUEST_CONTRACT_HMAC_TAG,
    ExistingTrainingJobMismatch,
    request_contract_hmac_key_from_environment,
    request_contract_hmac_sha256,
    validate_existing_training_job,
    with_request_contract_hmac_tag,
)

ROOT = Path(__file__).resolve().parents[2]
TRAIN_WORKFLOW = ROOT / ".github" / "workflows" / "train.yml"
POLL_ACTION = ROOT / ".github" / "actions" / "poll-sagemaker-training" / "action.yml"
TEST_HMAC_KEY = bytes.fromhex("11" * 32)


def _unstamped_request() -> dict[str, object]:
    return {
        "TrainingJobName": "product-search-ranking-prod-final-h0123456789abcdef",
        "RoleArn": "arn:aws:iam::000000000000:role/training",
        "AlgorithmSpecification": {
            "TrainingImage": "000000000000.dkr.ecr.us-east-1.amazonaws.com/train@sha256:abc",
            "TrainingInputMode": "File",
        },
        "InputDataConfig": [
            {
                "ChannelName": "training",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": "s3://private-bucket/runs/example/training-input/",
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
            },
            {
                "ChannelName": "config",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": "s3://private-bucket/runs/example/config/",
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
            },
        ],
        "OutputDataConfig": {"S3OutputPath": "s3://private-bucket/runs/example/output/"},
        "ResourceConfig": {
            "InstanceType": "ml.g4dn.xlarge",
            "InstanceCount": 1,
            "VolumeSizeInGB": 50,
        },
        "StoppingCondition": {
            "MaxRuntimeInSeconds": 18_000,
            "MaxWaitTimeInSeconds": 19_800,
        },
        "EnableManagedSpotTraining": True,
        "CheckpointConfig": {
            "S3Uri": "s3://private-bucket/runs/example/checkpoints/",
            "LocalPath": "/opt/ml/checkpoints",
        },
        "Environment": {
            "RUN_ID": "product-search-ranking-prod-final-h0123456789abcdef",
            "CODE_COMMIT": "a" * 40,
            "ALLOW_HELDOUT_EVAL": "0",
        },
        "Tags": [
            {"Key": "Project", "Value": "product-search-ranking"},
            {"Key": "RunKind", "Value": "final"},
            {"Key": "CodeCommit", "Value": "a" * 40},
        ],
    }


def _expected_request() -> dict[str, object]:
    return with_request_contract_hmac_tag(_unstamped_request(), TEST_HMAC_KEY)


def _validate(
    expected: dict[str, object],
    description: dict[str, object],
    tags: dict[str, object],
) -> None:
    validate_existing_training_job(expected, description, tags, TEST_HMAC_KEY)


def _aws_readback() -> tuple[dict[str, object], dict[str, object]]:
    expected = _expected_request()
    description = copy.deepcopy(expected)
    description.pop("Tags")
    description.update(
        {
            "TrainingJobArn": (
                "arn:aws:sagemaker:us-east-1:000000000000:training-job/"
                "product-search-ranking-prod-final-h0123456789abcdef"
            ),
            "TrainingJobStatus": "Completed",
            "HyperParameters": {},
            "EnableNetworkIsolation": False,
            "EnableInterContainerTrafficEncryption": False,
            "DebugRuleConfigurations": [],
            "ExperimentConfig": {},
            "ProfilerConfig": {},
            "ProfilerRuleConfigurations": [],
            "RemoteDebugConfig": {"EnableRemoteDebug": False},
            "InfraCheckConfig": {"EnableInfraCheck": False},
            "ResourceConfig": {
                **description["ResourceConfig"],  # type: ignore[dict-item]
                "KeepAlivePeriodInSeconds": 0,
            },
        }
    )
    algorithm = description["AlgorithmSpecification"]
    assert isinstance(algorithm, dict)
    algorithm.update(
        {
            "EnableSageMakerMetricsTimeSeries": False,
            "MetricDefinitions": [],
        }
    )
    output = description["OutputDataConfig"]
    assert isinstance(output, dict)
    output["CompressionType"] = "GZIP"
    channels = description["InputDataConfig"]
    assert isinstance(channels, list)
    channels.reverse()
    for channel in channels:
        assert isinstance(channel, dict)
        channel.update(
            {
                "CompressionType": "None",
                "RecordWrapperType": "None",
                "InputMode": "File",
            }
        )
    tags = {
        "Tags": [
            {"Key": "aws:createdBy", "Value": "managed"},
            {"Key": "sagemaker:domain-arn", "Value": "managed"},
            *reversed(expected["Tags"]),  # type: ignore[arg-type]
        ]
    }
    return description, tags


def test_training_polling_refreshes_credentials_and_covers_maximum_spot_wait() -> None:
    workflow = yaml.safe_load(TRAIN_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["submit"]
    steps = job["steps"]
    polling = [
        step for step in steps if str(step.get("uses", "")).endswith("poll-sagemaker-training")
    ]
    refreshes = [
        step
        for step in steps
        if str(step.get("name", "")).startswith("Refresh AWS credentials for training poll")
    ]
    final_refresh = next(
        step
        for step in steps
        if step.get("name") == "Refresh AWS credentials for final training evidence"
    )
    action = yaml.safe_load(POLL_ACTION.read_text(encoding="utf-8"))
    window_seconds = int(action["inputs"]["window-seconds"]["default"])

    assert job["timeout-minutes"] == 360
    assert job["env"]["TRAINING_REQUEST_CONTRACT_HMAC_KEY"] == (
        "${{ secrets.AWS_FINANCIAL_SNAPSHOT_HMAC_KEY }}"
    )
    assert len(polling) == len(refreshes) == 7
    assert len(polling) * window_seconds >= 19_800
    assert window_seconds + 20 < 3_600
    for refresh in (*refreshes, final_refresh):
        assert refresh["uses"] == (
            "aws-actions/configure-aws-credentials@cbe3b392738ccf3f987d68400dafcf4b0624a56c"
        )
        assert "role-duration-seconds" not in refresh["with"]
    for poll, refresh in zip(polling, refreshes, strict=True):
        assert steps.index(refresh) + 1 == steps.index(poll)
    assert steps.index(final_refresh) + 1 == next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Capture completion and sanitized evidence"
    )


def test_retry_readback_accepts_only_aws_defaults_and_order_drift() -> None:
    expected = _expected_request()
    description, tags = _aws_readback()

    _validate(expected, description, tags)


@pytest.mark.parametrize(
    ("field", "value", "label"),
    (
        ("HyperParameters", {"learning-rate": "sensitive"}, "hyperparameters"),
        (
            "VpcConfig",
            {"SecurityGroupIds": ["sg-sensitive"], "Subnets": []},
            "vpc",
        ),
        ("EnableNetworkIsolation", True, "network-isolation"),
        (
            "EnableInterContainerTrafficEncryption",
            True,
            "inter-container-traffic-encryption",
        ),
        ("DebugHookConfig", {"S3OutputPath": "s3://sensitive"}, "debug-hook"),
        (
            "DebugRuleConfigurations",
            [{"RuleConfigurationName": "sensitive"}],
            "debug-rules",
        ),
        (
            "TensorBoardOutputConfig",
            {"S3OutputPath": "s3://sensitive"},
            "tensorboard-output",
        ),
        ("ExperimentConfig", {"ExperimentName": "sensitive"}, "experiment"),
        (
            "ProfilerConfig",
            {"ProfilingIntervalInMilliseconds": 1_000},
            "profiler",
        ),
        (
            "ProfilerRuleConfigurations",
            [{"RuleConfigurationName": "sensitive"}],
            "profiler-rules",
        ),
        ("RetryStrategy", {"MaximumRetryAttempts": 1}, "retry-strategy"),
        ("RemoteDebugConfig", {"EnableRemoteDebug": True}, "remote-debug"),
        ("InfraCheckConfig", {"EnableInfraCheck": True}, "infra-check"),
        (
            "ServerlessJobConfig",
            {"BaseModelArn": "sensitive"},
            "serverless-job",
        ),
        ("MlflowConfig", {"MlflowResourceArn": "sensitive"}, "mlflow"),
        (
            "ModelPackageConfig",
            {"ModelPackageGroupArn": "sensitive"},
            "model-package",
        ),
    ),
)
def test_retry_readback_rejects_every_non_default_omitted_control(
    field: str,
    value: object,
    label: str,
) -> None:
    expected = _expected_request()
    description, tags = _aws_readback()
    description[field] = copy.deepcopy(value)

    with pytest.raises(ExistingTrainingJobMismatch, match=f"^{label}$") as error:
        _validate(expected, description, tags)

    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "label"),
    (
        ("VpcConfig", "vpc"),
        ("DebugHookConfig", "debug-hook"),
        ("TensorBoardOutputConfig", "tensorboard-output"),
        ("RetryStrategy", "retry-strategy"),
        ("ServerlessJobConfig", "serverless-job"),
        ("MlflowConfig", "mlflow"),
        ("ModelPackageConfig", "model-package"),
    ),
)
def test_retry_readback_rejects_illegal_empty_absence_only_controls(
    field: str,
    label: str,
) -> None:
    expected = _expected_request()
    description, tags = _aws_readback()
    description[field] = {}

    with pytest.raises(ExistingTrainingJobMismatch, match=f"^{label}$"):
        _validate(expected, description, tags)


def test_request_contract_hmac_binds_unobservable_session_chaining() -> None:
    safe_request = _expected_request()
    unsafe_request = _unstamped_request()
    unsafe_request["SessionChainingConfig"] = {"EnableSessionTagChaining": True}
    unsafe_request["Tags"] = copy.deepcopy(safe_request["Tags"])
    description, safe_tags = _aws_readback()

    assert request_contract_hmac_sha256(
        unsafe_request, TEST_HMAC_KEY
    ) != request_contract_hmac_sha256(safe_request, TEST_HMAC_KEY)
    with pytest.raises(ExistingTrainingJobMismatch, match=r"^request-contract$"):
        _validate(unsafe_request, description, safe_tags)


@pytest.mark.parametrize("mode", ("missing", "malformed", "spoofed"))
def test_expected_request_contract_hmac_must_be_present_and_authentic(mode: str) -> None:
    expected = _expected_request()
    description, tags = _aws_readback()
    digest_tag = next(tag for tag in expected["Tags"] if tag["Key"] == REQUEST_CONTRACT_HMAC_TAG)
    if mode == "missing":
        expected["Tags"].remove(digest_tag)
    elif mode == "malformed":
        digest_tag["Value"] = "sensitive-malformed-hmac"
    else:
        digest_tag["Value"] = "hmac-sha256:" + "0" * 64

    with pytest.raises(ExistingTrainingJobMismatch, match=r"^request-contract$") as error:
        _validate(expected, description, tags)

    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("mode", ("missing", "malformed", "spoofed"))
def test_actual_request_contract_hmac_tag_must_exactly_match_expected(mode: str) -> None:
    expected = _expected_request()
    description, tags = _aws_readback()
    digest_tag = next(tag for tag in tags["Tags"] if tag["Key"] == REQUEST_CONTRACT_HMAC_TAG)
    if mode == "missing":
        tags["Tags"].remove(digest_tag)
    elif mode == "malformed":
        digest_tag["Value"] = "sensitive-malformed-hmac"
    else:
        digest_tag["Value"] = "hmac-sha256:" + "0" * 64

    with pytest.raises(ExistingTrainingJobMismatch, match=r"^request-contract$") as error:
        _validate(expected, description, tags)

    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("field", tuple(_unstamped_request()))
def test_every_expected_request_field_changes_the_contract_hmac(field: str) -> None:
    request = _unstamped_request()
    baseline = request_contract_hmac_sha256(request, TEST_HMAC_KEY)
    mutated = copy.deepcopy(request)
    value = mutated[field]
    if isinstance(value, str):
        mutated[field] = value + "-mutation"
    elif isinstance(value, bool):
        mutated[field] = not value
    elif isinstance(value, dict):
        value["ContractMutation"] = "sensitive"
    elif isinstance(value, list):
        if field == "Tags":
            value.append({"Key": "ContractMutation", "Value": "sensitive"})
        else:
            value.append({"ContractMutation": "sensitive"})
    else:
        raise AssertionError(f"unhandled request field type for {field}")

    assert request_contract_hmac_sha256(mutated, TEST_HMAC_KEY) != baseline


def test_request_contract_hmac_is_independent_of_user_tag_order() -> None:
    request = _unstamped_request()
    reordered = copy.deepcopy(request)
    reordered["Tags"].reverse()

    assert request_contract_hmac_sha256(reordered, TEST_HMAC_KEY) == request_contract_hmac_sha256(
        request, TEST_HMAC_KEY
    )


def test_request_contract_cli_key_uses_only_the_distinct_training_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FINANCIAL_SNAPSHOT_HMAC_KEY", TEST_HMAC_KEY.hex())
    monkeypatch.delenv("TRAINING_REQUEST_CONTRACT_HMAC_KEY", raising=False)

    with pytest.raises(ExistingTrainingJobMismatch, match=r"^request-contract-key$"):
        request_contract_hmac_key_from_environment()


@pytest.mark.parametrize(
    "encoded",
    (
        "",
        "0" * 64,
        "1" * 63,
        "A" * 64,
        "g" * 64,
        "sensitive-malformed-key",
    ),
)
def test_request_contract_cli_key_rejects_placeholders_and_malformed_values(
    monkeypatch: pytest.MonkeyPatch,
    encoded: str,
) -> None:
    monkeypatch.setenv("TRAINING_REQUEST_CONTRACT_HMAC_KEY", encoded)

    with pytest.raises(ExistingTrainingJobMismatch, match=r"^request-contract-key$") as error:
        request_contract_hmac_key_from_environment()

    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("key", (b"", bytes(32), b"short"))
def test_pure_request_contract_hmac_rejects_invalid_keys(key: bytes) -> None:
    with pytest.raises(ExistingTrainingJobMismatch, match=r"^request-contract-key$"):
        request_contract_hmac_sha256(_unstamped_request(), key)


def test_request_contract_cli_key_accepts_exact_nonzero_lowercase_hex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAINING_REQUEST_CONTRACT_HMAC_KEY", TEST_HMAC_KEY.hex())

    assert request_contract_hmac_key_from_environment() == TEST_HMAC_KEY


def test_create_training_job_api_drift_requires_an_explicit_validation_decision() -> None:
    service = Session().get_service_model("sagemaker")
    create_shape = service.operation_model("CreateTrainingJob").input_shape
    describe_shape = service.operation_model("DescribeTrainingJob").output_shape
    assert create_shape is not None
    assert describe_shape is not None
    create_fields = set(create_shape.members)
    describe_fields = set(describe_shape.members)

    assert not (DIRECTLY_VALIDATED_CREATE_FIELDS & FINGERPRINT_ONLY_CREATE_FIELDS)
    assert create_fields == (DIRECTLY_VALIDATED_CREATE_FIELDS | FINGERPRINT_ONLY_CREATE_FIELDS)
    assert describe_fields | {"Tags"} >= DIRECTLY_VALIDATED_CREATE_FIELDS
    assert create_fields - describe_fields - {"Tags"} == FINGERPRINT_ONLY_CREATE_FIELDS


@pytest.mark.parametrize(
    ("mutation", "label"),
    (
        (
            lambda description, tags: description["AlgorithmSpecification"].__setitem__(
                "TrainingImage", "sensitive-mutated-image"
            ),
            "algorithm",
        ),
        (
            lambda description, tags: description["InputDataConfig"][0].__setitem__(
                "CompressionType", "Gzip"
            ),
            "input-data",
        ),
        (
            lambda description, tags: description["Environment"].__setitem__(
                "UNEXPECTED", "sensitive-unexpected-value"
            ),
            "environment",
        ),
        (
            lambda description, tags: tags["Tags"].append(
                {"Key": "UnexpectedUserTag", "Value": "sensitive-unexpected-value"}
            ),
            "tags",
        ),
    ),
)
def test_retry_readback_fails_closed_with_sanitized_field_diagnostics(
    mutation: object,
    label: str,
) -> None:
    expected = _expected_request()
    description, tags = _aws_readback()
    assert callable(mutation)
    mutation(description, tags)

    with pytest.raises(ExistingTrainingJobMismatch, match=f"^{label}$") as error:
        _validate(expected, description, tags)

    assert "sensitive" not in str(error.value)
