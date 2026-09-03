#!/usr/bin/env python3
"""Emit and revalidate sanitized provenance for protected financial inputs.

The protected values and HMAC key enter only this process and are never emitted.
The public receipt is a keyed commitment to the exact timestamp, source, spend,
applicable-credit strings, workflow, immutable operation-input digest, and commit.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from search_rank.schemas.workflow import (
    BenchmarkCostPreflight,
    EvaluationCostPreflight,
    ProtectedFinancialSnapshot,
    TrainingCostPreflight,
)

OBSERVED_AT_ENV = "FINANCIAL_SNAPSHOT_OBSERVED_AT"
RECEIPT_SHA256_ENV = "FINANCIAL_SNAPSHOT_RECEIPT_SHA256"
HMAC_KEY_ENV = "FINANCIAL_SNAPSHOT_HMAC_KEY"
SOURCE_ENV = "FINANCIAL_SNAPSHOT_SOURCE"
MAXIMUM_AGE_ENV = "FINANCIAL_SNAPSHOT_MAX_AGE_SECONDS"
CAMPAIGN_SPEND_ENV = "CAMPAIGN_SPEND_TO_DATE_USD"
REMAINING_CREDIT_ENV = "REMAINING_APPLICABLE_CREDIT_USD"
AUTHORIZATION_WORKFLOW_ENV = "FINANCIAL_SNAPSHOT_AUTHORIZATION_WORKFLOW"
AUTHORIZATION_INPUTS_JSON_ENV = "FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON"
AUTHORIZATION_COMMIT_ENV = "FINANCIAL_SNAPSHOT_AUTHORIZATION_COMMIT_SHA"
RESERVATION_MAX_USD_ENV = "FINANCIAL_RESERVATION_MAX_USD"
RESERVATION_REMAINING_USD_ENV = "FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD"
RESERVATION_CPU_HOURS_ENV = "FINANCIAL_RESERVATION_CPU_HOURS"
RESERVATION_GPU_HOURS_ENV = "FINANCIAL_RESERVATION_GPU_HOURS"
CPU_HOURS_USED_ENV = "FINANCIAL_CPU_HOURS_USED_TO_DATE"
GPU_HOURS_USED_ENV = "FINANCIAL_GPU_HOURS_USED_TO_DATE"
CAMPAIGN_BUDGET_ENV = "CAMPAIGN_BUDGET_USD"
REQUIRED_CREDIT_RESERVE_ENV = "REQUIRED_CREDIT_RESERVE_USD"
MAXIMUM_OUT_OF_POCKET_ENV = "MAXIMUM_OUT_OF_POCKET_USD"
EXPECTED_SOURCE = "aws_billing_and_cost_management_console"
MAXIMUM_AGE_SECONDS = 21_600
RECEIPT_PATTERN = re.compile(r"^sha256:(?!0{64}$)[0-9a-f]{64}$")
HMAC_KEY_PATTERN = re.compile(r"^(?!0{64}$)[0-9a-f]{64}$")
WORKFLOW_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
INPUT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
RECEIPT_BINDING_ALGORITHM = "hmac-sha256-v2"


class FinancialSnapshotError(ValueError):
    """A protected financial snapshot is missing, malformed, or stale."""


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not value:
        raise FinancialSnapshotError(f"missing protected snapshot field {name}")
    return value


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinancialSnapshotError("snapshot observation time must be RFC 3339") from exc
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None:
        raise FinancialSnapshotError("snapshot observation time must include a UTC offset")
    if offset != timedelta(0):
        raise FinancialSnapshotError("snapshot observation time must use UTC")
    return parsed.astimezone(UTC)


def _utc_now(now: datetime | None) -> datetime:
    checked_at = now if now is not None else datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise FinancialSnapshotError("validation time must be timezone-aware")
    return checked_at.astimezone(UTC)


def _protected_decimal(environment: Mapping[str, str], name: str) -> str:
    raw = _required(environment, name)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise FinancialSnapshotError("protected financial values must be decimal numbers") from exc
    if not value.is_finite() or value < 0:
        raise FinancialSnapshotError("protected financial values must be finite and non-negative")
    return raw


def reservation_payload(environment: Mapping[str, str]) -> dict[str, str]:
    """Return the exact signed budget state and conservative operation reservation."""

    return {
        "campaign_budget_usd": _protected_decimal(environment, CAMPAIGN_BUDGET_ENV),
        "required_credit_reserve_usd": _protected_decimal(environment, REQUIRED_CREDIT_RESERVE_ENV),
        "maximum_out_of_pocket_usd": _protected_decimal(environment, MAXIMUM_OUT_OF_POCKET_ENV),
        "reservation_max_usd": _protected_decimal(environment, RESERVATION_MAX_USD_ENV),
        "reservation_remaining_committed_usd": _protected_decimal(
            environment, RESERVATION_REMAINING_USD_ENV
        ),
        "reservation_cpu_hours": _protected_decimal(environment, RESERVATION_CPU_HOURS_ENV),
        "reservation_gpu_hours": _protected_decimal(environment, RESERVATION_GPU_HOURS_ENV),
        "cpu_hours_used_to_date": _protected_decimal(environment, CPU_HOURS_USED_ENV),
        "gpu_hours_used_to_date": _protected_decimal(environment, GPU_HOURS_USED_ENV),
    }


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant {value}")


def authorization_scope(environment: Mapping[str, str]) -> dict[str, str]:
    """Derive the exact public operation scope independently of the receipt."""

    workflow = _required(environment, AUTHORIZATION_WORKFLOW_ENV)
    if WORKFLOW_PATTERN.fullmatch(workflow) is None:
        raise FinancialSnapshotError("authorization workflow is malformed")
    commit_sha = _required(environment, AUTHORIZATION_COMMIT_ENV)
    if COMMIT_PATTERN.fullmatch(commit_sha) is None:
        raise FinancialSnapshotError("authorization commit must be a full lowercase Git SHA")
    raw_inputs = _required(environment, AUTHORIZATION_INPUTS_JSON_ENV)
    try:
        inputs = json.loads(raw_inputs, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FinancialSnapshotError("authorization inputs must be strict JSON") from exc
    if not isinstance(inputs, dict):
        raise FinancialSnapshotError("authorization inputs must be a JSON object")
    if any(INPUT_NAME_PATTERN.fullmatch(name) is None for name in inputs):
        raise FinancialSnapshotError("authorization input names are malformed")
    if any(isinstance(value, (dict, list)) for value in inputs.values()):
        raise FinancialSnapshotError("authorization input values must be JSON scalars")
    try:
        canonical_inputs = json.dumps(
            inputs,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FinancialSnapshotError("authorization input values are unsupported") from exc
    input_sha256 = "sha256:" + hashlib.sha256(canonical_inputs).hexdigest()
    reservation = reservation_payload(environment)
    reservation_sha256 = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                reservation,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    )
    operation_payload = json.dumps(
        {
            "authorization_commit_sha": commit_sha,
            "authorization_input_sha256": input_sha256,
            "authorization_workflow": workflow,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "authorization_workflow": workflow,
        "authorization_operation_id": "sha256:" + hashlib.sha256(operation_payload).hexdigest(),
        "authorization_input_sha256": input_sha256,
        "authorization_commit_sha": commit_sha,
        "authorization_reservation_sha256": reservation_sha256,
    }


def _binding_payload(environment: Mapping[str, str]) -> bytes:
    """Return an unambiguous encoding of the exact protected snapshot strings."""

    observed_at = _required(environment, OBSERVED_AT_ENV)
    _utc_datetime(observed_at)
    source = _required(environment, SOURCE_ENV)
    if source != EXPECTED_SOURCE:
        raise FinancialSnapshotError("snapshot source is not the approved AWS billing console")
    payload = {
        "binding_version": RECEIPT_BINDING_ALGORITHM,
        "authorization_scope": authorization_scope(environment),
        "authorization_reservation": reservation_payload(environment),
        "campaign_spend_to_date_usd": _protected_decimal(environment, CAMPAIGN_SPEND_ENV),
        "observed_at": observed_at,
        "remaining_applicable_credit_usd": _protected_decimal(environment, REMAINING_CREDIT_ENV),
        "source": source,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def compute_receipt_sha256(environment: Mapping[str, str]) -> str:
    """Compute the publishable keyed commitment without exposing its inputs."""

    raw_key = _required(environment, HMAC_KEY_ENV)
    if HMAC_KEY_PATTERN.fullmatch(raw_key) is None:
        raise FinancialSnapshotError(
            "snapshot HMAC key must be a non-placeholder 256-bit lowercase hexadecimal key"
        )
    digest = hmac.new(
        bytes.fromhex(raw_key),
        _binding_payload(environment),
        hashlib.sha256,
    ).hexdigest()
    return "sha256:" + digest


def build_snapshot(
    environment: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> ProtectedFinancialSnapshot:
    """Build sanitized evidence, failing closed on missing or stale provenance."""

    observed_at = _utc_datetime(_required(environment, OBSERVED_AT_ENV))
    scope = authorization_scope(environment)
    source = _required(environment, SOURCE_ENV)
    if source != EXPECTED_SOURCE:
        raise FinancialSnapshotError("snapshot source is not the approved AWS billing console")
    receipt_sha256 = _required(environment, RECEIPT_SHA256_ENV)
    if RECEIPT_PATTERN.fullmatch(receipt_sha256) is None:
        raise FinancialSnapshotError(
            "snapshot receipt must be a non-placeholder SHA-256 identifier"
        )
    expected_receipt = compute_receipt_sha256(environment)
    if not hmac.compare_digest(receipt_sha256, expected_receipt):
        raise FinancialSnapshotError(
            "snapshot receipt is not bound to the protected financial values and authorization scope"
        )
    raw_maximum_age = _required(environment, MAXIMUM_AGE_ENV)
    if raw_maximum_age != str(MAXIMUM_AGE_SECONDS):
        raise FinancialSnapshotError("snapshot maximum age must be exactly six hours")

    validated_at = _utc_now(now)
    elapsed_seconds = (validated_at - observed_at).total_seconds()
    if elapsed_seconds < 0:
        raise FinancialSnapshotError("snapshot observation time is in the future")
    age_seconds = math.ceil(elapsed_seconds)
    if age_seconds > MAXIMUM_AGE_SECONDS:
        raise FinancialSnapshotError("protected financial snapshot is stale")

    return ProtectedFinancialSnapshot.model_validate(
        {
            "schema_version": "1.0.0",
            "observed_at": observed_at,
            "validated_at": validated_at,
            "maximum_age_seconds": MAXIMUM_AGE_SECONDS,
            "age_seconds_at_validation": age_seconds,
            "source": source,
            **scope,
            "receipt_binding_algorithm": RECEIPT_BINDING_ALGORITHM,
            "receipt_sha256": receipt_sha256,
            "campaign_spend_to_date_redacted": True,
            "remaining_applicable_credit_redacted": True,
        }
    )


def verify_cost_preflight(
    path: Path,
    environment: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> ProtectedFinancialSnapshot:
    """Validate a cost preflight and re-check its protected snapshot at submission."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinancialSnapshotError("cost preflight is unavailable or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise FinancialSnapshotError("cost preflight must be a JSON object")
    cost_preflight: TrainingCostPreflight | EvaluationCostPreflight | BenchmarkCostPreflight
    try:
        artifact_type = payload.get("artifact_type")
        if artifact_type == "training_cost_preflight":
            cost_preflight = TrainingCostPreflight.model_validate(payload)
        elif artifact_type == "evaluation_cost_preflight":
            cost_preflight = EvaluationCostPreflight.model_validate(payload)
        elif artifact_type == "benchmark_cost_preflight":
            cost_preflight = BenchmarkCostPreflight.model_validate(payload)
        else:
            raise FinancialSnapshotError("cost preflight has an unsupported artifact type")
    except ValidationError as exc:
        raise FinancialSnapshotError("cost preflight schema validation failed") from exc

    current = build_snapshot(environment, now=now)
    recorded = cost_preflight.financial_snapshot
    if (
        recorded.observed_at != current.observed_at
        or recorded.source != current.source
        or recorded.authorization_workflow != current.authorization_workflow
        or recorded.authorization_operation_id != current.authorization_operation_id
        or recorded.authorization_input_sha256 != current.authorization_input_sha256
        or recorded.authorization_commit_sha != current.authorization_commit_sha
        or recorded.authorization_reservation_sha256 != current.authorization_reservation_sha256
        or recorded.receipt_binding_algorithm != current.receipt_binding_algorithm
        or recorded.receipt_sha256 != current.receipt_sha256
        or recorded.maximum_age_seconds != current.maximum_age_seconds
    ):
        raise FinancialSnapshotError("cost preflight is not bound to the protected snapshot")
    return recorded


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    emit = subparsers.add_parser("emit")
    emit.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--cost-preflight", type=Path, required=True)
    subparsers.add_parser("receipt")
    subparsers.add_parser("scope")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> int:
    args = _parser().parse_args(argv)
    values = os.environ if environment is None else environment
    try:
        if args.command == "emit":
            snapshot = build_snapshot(values, now=now)
            args.output.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
        elif args.command == "verify":
            verify_cost_preflight(args.cost_preflight, values, now=now)
        elif args.command == "receipt":
            print(compute_receipt_sha256(values))
        else:
            print(json.dumps(authorization_scope(values), indent=2, sort_keys=True))
    except (FinancialSnapshotError, OSError):
        print(
            "Financial snapshot rejected; verify its protected UTC timestamp, source, "
            "HMAC-bound operation scope, finite balances, and six-hour TTL.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
