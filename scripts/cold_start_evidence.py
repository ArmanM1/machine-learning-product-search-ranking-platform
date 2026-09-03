"""Build sanitized evidence for one controlled, on-demand Lambda cold start."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _finite_number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{label} must be finite and {qualifier}")
    return result


def _parse_iso8601(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty ISO-8601 timestamp")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(UTC)


def _message_json(message: object) -> dict[str, Any] | None:
    if not isinstance(message, str):
        return None
    candidates = [message]
    opening = message.find("{")
    if opening > 0:
        candidates.append(message[opening:])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        record = value.get("record")
        if isinstance(record, str):
            nested = _message_json(record)
            if nested is not None:
                return nested
        return value
    return None


def _report_metrics(message: object) -> dict[str, float] | None:
    structured = _message_json(message)
    if structured is not None and structured.get("type") == "platform.report":
        record = structured.get("record")
        metrics = record.get("metrics") if isinstance(record, dict) else None
        if isinstance(metrics, dict):
            aliases = {
                "duration_ms": "durationMs",
                "billed_duration_ms": "billedDurationMs",
                "memory_size_mb": "memorySizeMB",
                "max_memory_used_mb": "maxMemoryUsedMB",
                "init_duration_ms": "initDurationMs",
            }
            if all(key in metrics for key in aliases.values()):
                return {
                    name: _finite_number(metrics[key], f"Lambda report {key}", positive=True)
                    for name, key in aliases.items()
                }

    if not isinstance(message, str) or "REPORT RequestId:" not in message:
        return None
    patterns = {
        "duration_ms": r"(?:^|\s)Duration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms",
        "billed_duration_ms": r"Billed Duration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms",
        "memory_size_mb": r"Memory Size:\s*([0-9]+(?:\.[0-9]+)?)\s*MB",
        "max_memory_used_mb": r"Max Memory Used:\s*([0-9]+(?:\.[0-9]+)?)\s*MB",
        "init_duration_ms": r"Init Duration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms",
    }
    values: dict[str, float] = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, message)
        if match is None:
            return None
        values[name] = _finite_number(float(match.group(1)), f"Lambda report {name}", positive=True)
    return values


def _events(payload: dict[str, Any], label: str) -> list[dict[str, Any]]:
    value = payload.get("events")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must contain a CloudWatch events array")
    return value


def build_evidence(
    *,
    function_metadata: dict[str, Any],
    prior_events: dict[str, Any],
    observed_events: dict[str, Any],
    response: dict[str, Any],
    function_name: str,
    alias: str,
    version: str,
    previous_version: str,
    release_id: str,
    expected_model_id: str,
    expected_dataset_hash: str,
    expected_model_checksum: str,
    request_id: str,
    request_started_at: str,
    end_to_end_ms: float,
    candidate_count: int,
    apply_started_epoch_ms: int,
) -> dict[str, Any]:
    if not re.fullmatch(r"[1-9][0-9]*", version):
        raise ValueError("candidate Lambda version must be numeric and published")
    if alias != "candidate":
        raise ValueError("controlled cold-start evidence must use the candidate alias")
    if previous_version != "absent":
        if not re.fullmatch(r"[1-9][0-9]*", previous_version):
            raise ValueError("previous candidate version must be numeric or absent")
        if previous_version == version:
            raise ValueError("candidate version did not change during deployment")
    if not request_id or len(request_id) > 128:
        raise ValueError("request ID must be present and bounded")
    if not 1 <= candidate_count <= 40:
        raise ValueError("candidate count must be between one and 40")

    configuration = function_metadata.get("Configuration")
    concurrency = function_metadata.get("Concurrency")
    if not isinstance(configuration, dict) or not isinstance(concurrency, dict):
        raise ValueError("GetFunction metadata is missing configuration or concurrency")
    architectures = configuration.get("Architectures")
    memory_mb = configuration.get("MemorySize")
    if configuration.get("FunctionName") != function_name:
        raise ValueError("GetFunction metadata names a different function")
    if configuration.get("Version") != version:
        raise ValueError("GetFunction metadata names a different published version")
    if architectures != ["x86_64"] or memory_mb != 4096:
        raise ValueError("Lambda architecture and memory must remain x86_64/4096 MB")
    if concurrency.get("ReservedConcurrentExecutions") != 2:
        raise ValueError("Lambda reserved concurrency must remain exactly two")
    last_modified = _parse_iso8601(configuration.get("LastModified"), "Lambda LastModified")
    if int(last_modified.timestamp() * 1000) < apply_started_epoch_ms:
        raise ValueError("candidate version was not newly published by this deployment apply")

    prior = _events(prior_events, "prior events")
    version_marker = f"[{version}]"
    prior_for_version = [
        event for event in prior if version_marker in str(event.get("logStreamName", ""))
    ]
    if prior_for_version:
        raise ValueError("candidate version had CloudWatch events before the measured request")

    observed = _events(observed_events, "observed events")
    correlated_streams = {
        str(event.get("logStreamName"))
        for event in observed
        if request_id in str(event.get("message", ""))
        and version_marker in str(event.get("logStreamName", ""))
    }
    if len(correlated_streams) != 1:
        raise ValueError("measured request must correlate to exactly one versioned log stream")
    stream = next(iter(correlated_streams))
    correlated = [event for event in observed if event.get("logStreamName") == stream]
    structured = [_message_json(event.get("message")) for event in correlated]
    startup_events = [
        event
        for event in structured
        if event is not None and event.get("message") == "service_startup_success"
    ]
    request_events = [
        event
        for event in structured
        if event is not None
        and event.get("message") == "api_request"
        and event.get("request_id") == request_id
    ]
    reports = [
        report
        for event in correlated
        if (report := _report_metrics(event.get("message"))) is not None
    ]
    if len(startup_events) != 1 or len(request_events) != 1 or len(reports) != 1:
        raise ValueError("cold invocation needs one startup, request, and Lambda REPORT event")
    startup = startup_events[0]
    request = request_events[0]
    report = reports[0]

    if (
        startup.get("startup_success") is not True
        or startup.get("model_id") != expected_model_id
        or request.get("route") != "/api/v1/rank"
        or request.get("model_id") != expected_model_id
        or request.get("candidate_count") != candidate_count
        or request.get("status_code") != 200
        or request.get("error_code") is not None
    ):
        raise ValueError(
            "structured startup or request event is not bound to the measured rank call"
        )
    model_load_ms = _finite_number(
        startup.get("model_load_duration_ms"), "structured model-load duration", positive=True
    )
    process_peak_memory_mb = _finite_number(
        request.get("memory_used_mb"), "structured process peak memory", positive=True
    )
    model_latency_ms = _finite_number(response.get("latency_ms"), "rank response model latency")
    if (
        response.get("query_id") != request.get("query_id")
        or response.get("model_id") != expected_model_id
        or response.get("dataset_manifest_hash") != expected_dataset_hash
        or response.get("model_artifact_checksum") != expected_model_checksum
        or response.get("candidate_count") != candidate_count
        or response.get("top_k") != candidate_count
        or not isinstance(response.get("results"), list)
        or len(response["results"]) != candidate_count
    ):
        raise ValueError("rank response is not bound to the promoted release and measured request")

    if int(report["memory_size_mb"]) != memory_mb:
        raise ValueError("Lambda REPORT memory size differs from function configuration")
    if report["max_memory_used_mb"] > float(memory_mb):
        raise ValueError("Lambda REPORT max memory exceeds configured memory")
    request_time = _parse_iso8601(request_started_at, "request start")
    end_to_end = _finite_number(end_to_end_ms, "first-request end-to-end latency", positive=True)

    return {
        "schema_version": "1.0.0",
        "status": "measured",
        "measurement_class": "controlled_on_demand_lambda_cold_start",
        "controlled_cold_start": True,
        "measured_at": request_time.isoformat(),
        "identifiers": {
            "release_id": release_id,
            "model_id": expected_model_id,
            "dataset_manifest_hash": expected_dataset_hash,
            "model_artifact_checksum": expected_model_checksum,
            "function_name": function_name,
            "alias": alias,
            "function_version": version,
            "region": "us-east-1",
        },
        "control_proof": {
            "newly_published_after_apply_started": True,
            "candidate_version_changed": True,
            "previous_candidate_version": previous_version,
            "new_version_prior_cloudwatch_event_count": 0,
            "on_demand_execution": True,
            "reserved_concurrency": 2,
            "provisioned_concurrency": 0,
        },
        "first_request": {
            "request_id": request_id,
            "route": "/api/v1/rank",
            "http_status": 200,
            "candidate_count": candidate_count,
            "end_to_end_latency_ms": end_to_end,
            "model_latency_ms": model_latency_ms,
        },
        "lambda_report": {
            "init_duration_ms": report["init_duration_ms"],
            "invocation_duration_ms": report["duration_ms"],
            "billed_duration_ms": report["billed_duration_ms"],
            "configured_memory_mb": int(report["memory_size_mb"]),
            "max_memory_used_mb": report["max_memory_used_mb"],
        },
        "structured_startup": {
            "startup_succeeded": True,
            "model_load_duration_ms": model_load_ms,
        },
        "structured_request": {
            "process_peak_memory_mb": process_peak_memory_mb,
        },
        "sample_count": 1,
        "excluded_from_warm_samples": True,
        "limitations": [
            "This is one controlled cold-start observation, not a cold-latency distribution.",
            "End-to-end latency includes the private candidate API Gateway path and network time.",
            "CloudWatch max memory and process peak memory use different measurement scopes.",
        ],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--function-metadata", type=Path, required=True)
    parser.add_argument("--prior-events", type=Path, required=True)
    parser.add_argument("--observed-events", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--dataset-manifest-hash", required=True)
    parser.add_argument("--model-artifact-checksum", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--request-started-at", required=True)
    parser.add_argument("--end-to-end-ms", type=float, required=True)
    parser.add_argument("--candidate-count", type=int, required=True)
    parser.add_argument("--apply-started-epoch-ms", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = build_evidence(
            function_metadata=_load(args.function_metadata),
            prior_events=_load(args.prior_events),
            observed_events=_load(args.observed_events),
            response=_load(args.response),
            function_name=args.function_name,
            alias=args.alias,
            version=args.version,
            previous_version=args.previous_version,
            release_id=args.release_id,
            expected_model_id=args.model_id,
            expected_dataset_hash=args.dataset_manifest_hash,
            expected_model_checksum=args.model_artifact_checksum,
            request_id=args.request_id,
            request_started_at=args.request_started_at,
            end_to_end_ms=args.end_to_end_ms,
            candidate_count=args.candidate_count,
            apply_started_epoch_ms=args.apply_started_epoch_ms,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote controlled Lambda cold-start evidence to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
