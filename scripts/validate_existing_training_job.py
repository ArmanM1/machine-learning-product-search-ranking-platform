"""Validate that a described SageMaker job is safe to reuse on a workflow retry.

SageMaker's create and describe shapes are not byte-for-byte symmetric. In
particular, describe may add channel defaults and AWS-managed tags, and neither
channel nor tag order is contractual. This validator compares the fields that
define the submitted job while accepting only those documented readback
normalizations.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

JsonObject = Mapping[str, Any]
Normalizer = Callable[[JsonObject], object]

REQUEST_CONTRACT_HMAC_TAG = "RequestContractHmacSha256"
REQUEST_CONTRACT_HMAC_DOMAIN = b"product-search-ranking/sagemaker-create-request/v1\x00"
HMAC_SHA256 = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
HMAC_KEY_HEX = re.compile(r"^[0-9a-f]{64}$")

# Keep this allowlist synchronized with the botocore CreateTrainingJob model. The
# contract test deliberately fails when AWS adds a create-time control until its
# direct readback validation or fingerprint-only treatment is reviewed.
DIRECTLY_VALIDATED_CREATE_FIELDS = frozenset(
    {
        "AlgorithmSpecification",
        "CheckpointConfig",
        "DebugHookConfig",
        "DebugRuleConfigurations",
        "EnableInterContainerTrafficEncryption",
        "EnableManagedSpotTraining",
        "EnableNetworkIsolation",
        "Environment",
        "ExperimentConfig",
        "HyperParameters",
        "InfraCheckConfig",
        "InputDataConfig",
        "MlflowConfig",
        "ModelPackageConfig",
        "OutputDataConfig",
        "ProfilerConfig",
        "ProfilerRuleConfigurations",
        "RemoteDebugConfig",
        "ResourceConfig",
        "RetryStrategy",
        "RoleArn",
        "ServerlessJobConfig",
        "StoppingCondition",
        "Tags",
        "TensorBoardOutputConfig",
        "TrainingJobName",
        "VpcConfig",
    }
)
FINGERPRINT_ONLY_CREATE_FIELDS = frozenset({"SessionChainingConfig"})

AWS_MANAGED_SAGEMAKER_TAGS = frozenset(
    {
        "sagemaker:domain-arn",
        "sagemaker:space-arn",
        "sagemaker:user-profile-arn",
    }
)


class ExistingTrainingJobMismatch(ValueError):
    """Raised with a sanitized field label when an existing job is not reusable."""


def _object(value: object, label: str) -> JsonObject:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ExistingTrainingJobMismatch(label)
    return value


def _array(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ExistingTrainingJobMismatch(label)
    return value


def _field(payload: JsonObject, name: str, label: str) -> object:
    if name not in payload:
        raise ExistingTrainingJobMismatch(label)
    return payload[name]


def _require_only_keys(payload: JsonObject, allowed: set[str], label: str) -> None:
    if set(payload) - allowed:
        raise ExistingTrainingJobMismatch(label)


def _parsed_tags(payload: JsonObject, label: str) -> list[tuple[str, str]]:
    raw_tags = _array(_field(payload, "Tags", label), label)
    normalized: list[tuple[str, str]] = []
    keys: set[str] = set()
    for raw_tag in raw_tags:
        tag = _object(raw_tag, label)
        _require_only_keys(tag, {"Key", "Value"}, label)
        key = _field(tag, "Key", label)
        value = _field(tag, "Value", label)
        if not isinstance(key, str) or not isinstance(value, str) or key in keys:
            raise ExistingTrainingJobMismatch(label)
        keys.add(key)
        normalized.append((key, value))
    return normalized


def _validate_hmac_key(hmac_key: bytes) -> None:
    if type(hmac_key) is not bytes or len(hmac_key) != 32 or hmac_key == bytes(32):
        raise ExistingTrainingJobMismatch("request-contract-key")


def request_contract_hmac_sha256(request: JsonObject, hmac_key: bytes) -> str:
    """Authenticate the complete create request, excluding only its HMAC tag."""

    _validate_hmac_key(hmac_key)
    canonical = copy.deepcopy(dict(request))
    non_contract_tags = [
        tag
        for tag in _parsed_tags(request, "request-contract")
        if tag[0] != REQUEST_CONTRACT_HMAC_TAG
    ]
    canonical["Tags"] = [{"Key": key, "Value": value} for key, value in sorted(non_contract_tags)]
    try:
        encoded = json.dumps(
            canonical,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExistingTrainingJobMismatch("request-contract") from exc
    digest = hmac.new(
        hmac_key,
        REQUEST_CONTRACT_HMAC_DOMAIN + encoded,
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"


def with_request_contract_hmac_tag(request: JsonObject, hmac_key: bytes) -> dict[str, Any]:
    """Return a request carrying its verified, domain-separated contract HMAC tag."""

    tags = _parsed_tags(request, "request-contract")
    existing = [value for key, value in tags if key == REQUEST_CONTRACT_HMAC_TAG]
    digest = request_contract_hmac_sha256(request, hmac_key)
    if existing and (
        not HMAC_SHA256.fullmatch(existing[0]) or not hmac.compare_digest(existing[0], digest)
    ):
        raise ExistingTrainingJobMismatch("request-contract")

    stamped = copy.deepcopy(dict(request))
    stamped["Tags"] = [
        {"Key": key, "Value": value}
        for key, value in sorted(
            [tag for tag in tags if tag[0] != REQUEST_CONTRACT_HMAC_TAG]
            + [(REQUEST_CONTRACT_HMAC_TAG, digest)]
        )
    ]
    return stamped


def request_contract_hmac_key_from_environment() -> bytes:
    """Load the protected request-contract HMAC key without exposing its value."""

    encoded = os.environ.get("TRAINING_REQUEST_CONTRACT_HMAC_KEY", "")
    if not HMAC_KEY_HEX.fullmatch(encoded) or int(encoded, 16) == 0:
        raise ExistingTrainingJobMismatch("request-contract-key")
    return bytes.fromhex(encoded)


def _algorithm(payload: JsonObject) -> object:
    algorithm = _object(_field(payload, "AlgorithmSpecification", "algorithm"), "algorithm")
    _require_only_keys(
        algorithm,
        {
            "TrainingImage",
            "TrainingInputMode",
            "MetricDefinitions",
            "EnableSageMakerMetricsTimeSeries",
        },
        "algorithm",
    )
    metrics = algorithm.get("MetricDefinitions", [])
    metrics = _array(metrics, "algorithm")
    if metrics:
        raise ExistingTrainingJobMismatch("algorithm")
    metrics_enabled = algorithm.get("EnableSageMakerMetricsTimeSeries", False)
    if metrics_enabled is not False:
        raise ExistingTrainingJobMismatch("algorithm")
    return (
        _field(algorithm, "TrainingImage", "algorithm"),
        _field(algorithm, "TrainingInputMode", "algorithm"),
        tuple(metrics),
        metrics_enabled,
    )


def _input_channels(payload: JsonObject) -> object:
    channels = _array(_field(payload, "InputDataConfig", "input-data"), "input-data")
    normalized: list[tuple[object, ...]] = []
    names: set[object] = set()
    for raw_channel in channels:
        channel = _object(raw_channel, "input-data")
        _require_only_keys(
            channel,
            {
                "ChannelName",
                "DataSource",
                "CompressionType",
                "RecordWrapperType",
                "InputMode",
            },
            "input-data",
        )
        name = _field(channel, "ChannelName", "input-data")
        if not isinstance(name, str) or not name or name in names:
            raise ExistingTrainingJobMismatch("input-data")
        names.add(name)

        data_source = _object(_field(channel, "DataSource", "input-data"), "input-data")
        _require_only_keys(data_source, {"S3DataSource"}, "input-data")
        s3 = _object(_field(data_source, "S3DataSource", "input-data"), "input-data")
        _require_only_keys(
            s3,
            {"S3DataType", "S3Uri", "S3DataDistributionType"},
            "input-data",
        )

        # These fields are omitted by CreateTrainingJob in this workflow but may
        # be materialized with their effective defaults by DescribeTrainingJob.
        if channel.get("CompressionType", "None") != "None":
            raise ExistingTrainingJobMismatch("input-data")
        if channel.get("RecordWrapperType", "None") != "None":
            raise ExistingTrainingJobMismatch("input-data")
        if channel.get("InputMode", "File") != "File":
            raise ExistingTrainingJobMismatch("input-data")

        normalized.append(
            (
                name,
                _field(s3, "S3DataType", "input-data"),
                _field(s3, "S3Uri", "input-data"),
                _field(s3, "S3DataDistributionType", "input-data"),
            )
        )
    return tuple(sorted(normalized, key=lambda item: str(item[0])))


def _output(payload: JsonObject) -> object:
    output = _object(_field(payload, "OutputDataConfig", "output-data"), "output-data")
    _require_only_keys(output, {"S3OutputPath", "CompressionType"}, "output-data")
    compression = output.get("CompressionType", "GZIP")
    if compression != "GZIP":
        raise ExistingTrainingJobMismatch("output-data")
    return (_field(output, "S3OutputPath", "output-data"), compression)


def _resources(payload: JsonObject) -> object:
    resources = _object(_field(payload, "ResourceConfig", "resources"), "resources")
    _require_only_keys(
        resources,
        {"InstanceType", "InstanceCount", "VolumeSizeInGB", "KeepAlivePeriodInSeconds"},
        "resources",
    )
    keep_alive = resources.get("KeepAlivePeriodInSeconds", 0)
    if keep_alive != 0:
        raise ExistingTrainingJobMismatch("resources")
    return (
        *(
            _field(resources, field, "resources")
            for field in ("InstanceType", "InstanceCount", "VolumeSizeInGB")
        ),
        keep_alive,
    )


def _stopping_condition(payload: JsonObject) -> object:
    stopping = _object(
        _field(payload, "StoppingCondition", "stopping-condition"),
        "stopping-condition",
    )
    _require_only_keys(
        stopping,
        {"MaxRuntimeInSeconds", "MaxWaitTimeInSeconds"},
        "stopping-condition",
    )
    return tuple(
        _field(stopping, field, "stopping-condition")
        for field in ("MaxRuntimeInSeconds", "MaxWaitTimeInSeconds")
    )


def _checkpoint(payload: JsonObject) -> object:
    checkpoint = _object(
        _field(payload, "CheckpointConfig", "checkpoint"),
        "checkpoint",
    )
    _require_only_keys(checkpoint, {"S3Uri", "LocalPath"}, "checkpoint")
    return tuple(_field(checkpoint, field, "checkpoint") for field in ("S3Uri", "LocalPath"))


def _environment(payload: JsonObject) -> object:
    environment = _object(_field(payload, "Environment", "environment"), "environment")
    if not all(isinstance(value, str) for value in environment.values()):
        raise ExistingTrainingJobMismatch("environment")
    return dict(environment)


def _omitted_map(payload: JsonObject, field: str, label: str) -> None:
    if field not in payload:
        return
    value = _object(payload[field], label)
    if value:
        raise ExistingTrainingJobMismatch(label)


def _omitted_list(payload: JsonObject, field: str, label: str) -> None:
    if field not in payload:
        return
    value = _array(payload[field], label)
    if value:
        raise ExistingTrainingJobMismatch(label)


def _omitted_false(payload: JsonObject, field: str, label: str) -> None:
    if field in payload and payload[field] is not False:
        raise ExistingTrainingJobMismatch(label)


def _omitted_absent(payload: JsonObject, field: str, label: str) -> None:
    if field in payload:
        raise ExistingTrainingJobMismatch(label)


def _omitted_structure(
    payload: JsonObject,
    field: str,
    label: str,
    defaults: JsonObject,
) -> None:
    if field not in payload:
        return
    value = _object(payload[field], label)
    _require_only_keys(value, set(defaults), label)
    for key, actual in value.items():
        if not _strict_equal(actual, defaults[key]):
            raise ExistingTrainingJobMismatch(label)


FIELD_COMPARISONS: tuple[tuple[str, Normalizer], ...] = (
    ("training-job-name", lambda payload: _field(payload, "TrainingJobName", "training-job-name")),
    ("role", lambda payload: _field(payload, "RoleArn", "role")),
    ("algorithm", _algorithm),
    ("input-data", _input_channels),
    ("output-data", _output),
    ("resources", _resources),
    ("stopping-condition", _stopping_condition),
    (
        "managed-spot",
        lambda payload: _field(payload, "EnableManagedSpotTraining", "managed-spot"),
    ),
    ("checkpoint", _checkpoint),
    ("environment", _environment),
    (
        "hyperparameters",
        lambda payload: _omitted_map(payload, "HyperParameters", "hyperparameters"),
    ),
    (
        "vpc",
        lambda payload: _omitted_absent(payload, "VpcConfig", "vpc"),
    ),
    (
        "network-isolation",
        lambda payload: _omitted_false(
            payload,
            "EnableNetworkIsolation",
            "network-isolation",
        ),
    ),
    (
        "inter-container-traffic-encryption",
        lambda payload: _omitted_false(
            payload,
            "EnableInterContainerTrafficEncryption",
            "inter-container-traffic-encryption",
        ),
    ),
    (
        "debug-hook",
        lambda payload: _omitted_absent(payload, "DebugHookConfig", "debug-hook"),
    ),
    (
        "debug-rules",
        lambda payload: _omitted_list(
            payload,
            "DebugRuleConfigurations",
            "debug-rules",
        ),
    ),
    (
        "tensorboard-output",
        lambda payload: _omitted_absent(
            payload,
            "TensorBoardOutputConfig",
            "tensorboard-output",
        ),
    ),
    (
        "experiment",
        lambda payload: _omitted_structure(
            payload,
            "ExperimentConfig",
            "experiment",
            {},
        ),
    ),
    (
        "profiler",
        lambda payload: _omitted_structure(
            payload,
            "ProfilerConfig",
            "profiler",
            {},
        ),
    ),
    (
        "profiler-rules",
        lambda payload: _omitted_list(
            payload,
            "ProfilerRuleConfigurations",
            "profiler-rules",
        ),
    ),
    (
        "retry-strategy",
        lambda payload: _omitted_absent(payload, "RetryStrategy", "retry-strategy"),
    ),
    (
        "remote-debug",
        lambda payload: _omitted_structure(
            payload,
            "RemoteDebugConfig",
            "remote-debug",
            {"EnableRemoteDebug": False},
        ),
    ),
    (
        "infra-check",
        lambda payload: _omitted_structure(
            payload,
            "InfraCheckConfig",
            "infra-check",
            {"EnableInfraCheck": False},
        ),
    ),
    (
        "serverless-job",
        lambda payload: _omitted_absent(
            payload,
            "ServerlessJobConfig",
            "serverless-job",
        ),
    ),
    (
        "mlflow",
        lambda payload: _omitted_absent(payload, "MlflowConfig", "mlflow"),
    ),
    (
        "model-package",
        lambda payload: _omitted_absent(
            payload,
            "ModelPackageConfig",
            "model-package",
        ),
    ),
)


def _strict_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return len(left) == len(right) and all(
            _strict_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return bool(left == right)


def _tags(payload: JsonObject, *, expected: bool) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for key, value in _parsed_tags(payload, "tags"):
        if not expected and (key.startswith("aws:") or key in AWS_MANAGED_SAGEMAKER_TAGS):
            continue
        normalized.append((key, value))
    return tuple(sorted(normalized))


def _verify_request_contract_hmac(
    expected_request: JsonObject,
    tag_listing: JsonObject,
    hmac_key: bytes,
) -> None:
    expected_digests = [
        value
        for key, value in _parsed_tags(expected_request, "request-contract")
        if key == REQUEST_CONTRACT_HMAC_TAG
    ]
    if len(expected_digests) != 1 or not HMAC_SHA256.fullmatch(expected_digests[0]):
        raise ExistingTrainingJobMismatch("request-contract")
    recomputed = request_contract_hmac_sha256(expected_request, hmac_key)
    if not hmac.compare_digest(expected_digests[0], recomputed):
        raise ExistingTrainingJobMismatch("request-contract")

    actual_digests = [
        value
        for key, value in _parsed_tags(tag_listing, "request-contract")
        if key == REQUEST_CONTRACT_HMAC_TAG
    ]
    if (
        len(actual_digests) != 1
        or not HMAC_SHA256.fullmatch(actual_digests[0])
        or not hmac.compare_digest(actual_digests[0], expected_digests[0])
    ):
        raise ExistingTrainingJobMismatch("request-contract")


def validate_existing_training_job(
    expected_request: JsonObject,
    description: JsonObject,
    tag_listing: JsonObject,
    hmac_key: bytes,
) -> None:
    """Fail closed unless the existing job has the same effective request contract."""

    _verify_request_contract_hmac(expected_request, tag_listing, hmac_key)
    for label, normalize in FIELD_COMPARISONS:
        if not _strict_equal(normalize(description), normalize(expected_request)):
            raise ExistingTrainingJobMismatch(label)
    if not _strict_equal(
        _tags(tag_listing, expected=False),
        _tags(expected_request, expected=True),
    ):
        raise ExistingTrainingJobMismatch("tags")


def _read_object(path: Path, label: str) -> JsonObject:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExistingTrainingJobMismatch(label) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    stamp = commands.add_parser("stamp")
    stamp.add_argument("--request", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--expected-request", type=Path, required=True)
    validate.add_argument("--description", type=Path, required=True)
    validate.add_argument("--tags", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        hmac_key = request_contract_hmac_key_from_environment()
        if args.command == "stamp":
            stamped = with_request_contract_hmac_tag(
                _read_object(args.request, "expected-request"),
                hmac_key,
            )
            args.request.write_text(
                json.dumps(stamped, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            validate_existing_training_job(
                _read_object(args.expected_request, "expected-request"),
                _read_object(args.description, "description"),
                _read_object(args.tags, "tags"),
                hmac_key,
            )
    except ExistingTrainingJobMismatch as exc:
        raise SystemExit(f"Existing SageMaker training job cannot be reused: {exc}.") from None


if __name__ == "__main__":
    main()
