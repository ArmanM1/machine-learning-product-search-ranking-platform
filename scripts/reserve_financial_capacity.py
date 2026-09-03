#!/usr/bin/env python3
"""Atomically reserve bounded AWS campaign capacity in the Terraform state bucket.

The ledger deliberately never deletes a reservation. Aggregate commitments are scoped to the exact
authorization commit while every historical record remains auditable. Every update uses an S3 ETag
compare-and-swap (or If-None-Match for creation), so stale financial snapshots cannot race within
one immutable revision's shared campaign envelope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    from scripts.validate_financial_snapshot import (
        CAMPAIGN_SPEND_ENV,
        REMAINING_CREDIT_ENV,
        FinancialSnapshotError,
        authorization_scope,
        build_snapshot,
        reservation_payload,
    )
except ModuleNotFoundError:  # Direct execution places scripts/, rather than the repo root, on PATH.
    from validate_financial_snapshot import (  # type: ignore[import-not-found,no-redef]
        CAMPAIGN_SPEND_ENV,
        REMAINING_CREDIT_ENV,
        FinancialSnapshotError,
        authorization_scope,
        build_snapshot,
        reservation_payload,
    )

LEDGER_KEY = "cost-control/ledger.json"
LEDGER_SCHEMA_VERSION = "1.0.0"
PROOF_SCHEMA_VERSION = "1.0.0"
MAXIMUM_CAS_ATTEMPTS = 6
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
WORKFLOW_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
ETAG_PATTERN = re.compile(r'^"[0-9A-Fa-f]{32}(?:-[1-9][0-9]*)?"$')
APPROVED_POLICY = {
    "campaign_budget_usd": "40",
    "required_credit_reserve_usd": "40",
    "maximum_out_of_pocket_usd": "0",
    "maximum_cpu_hours": "10",
    "maximum_gpu_hours": "20",
}
SIGNED_RESERVATION_KEYS = {
    "campaign_budget_usd",
    "required_credit_reserve_usd",
    "maximum_out_of_pocket_usd",
    "reservation_max_usd",
    "reservation_remaining_committed_usd",
    "reservation_cpu_hours",
    "reservation_gpu_hours",
    "cpu_hours_used_to_date",
    "gpu_hours_used_to_date",
}
RECORD_KEYS = {
    "authorization_commit_sha",
    "authorization_input_sha256",
    "authorization_reservation_sha256",
    "authorization_workflow",
    "financial_snapshot_observed_at",
    "financial_snapshot_receipt_sha256",
    "reserved_at",
    "signed_reservation",
    "status",
}


class FinancialReservationError(ValueError):
    """The shared ledger or requested reservation is invalid or exceeds policy."""


class AwsCliError(RuntimeError):
    """A redacted AWS CLI operation failed."""

    def __init__(self, message: str, *, retryable_cas_conflict: bool = False) -> None:
        super().__init__(message)
        self.retryable_cas_conflict = retryable_cas_conflict


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FinancialReservationError("reservation time must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise FinancialReservationError(f"ledger {field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinancialReservationError(f"ledger {field} must be a UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise FinancialReservationError(f"ledger {field} must be a UTC timestamp")
    return value


def _decimal(value: object, *, field: str) -> Decimal:
    if not isinstance(value, str):
        raise FinancialReservationError(f"ledger {field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise FinancialReservationError(f"ledger {field} must be a decimal string") from exc
    if not parsed.is_finite() or parsed < 0:
        raise FinancialReservationError(f"ledger {field} must be finite and non-negative")
    return parsed


def _reservation_hash(reservation: Mapping[str, str]) -> str:
    payload = json.dumps(
        reservation,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def empty_ledger(*, now: datetime) -> dict[str, Any]:
    timestamp = _utc_timestamp(now)
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "created_at": timestamp,
        "updated_at": timestamp,
        "policy": dict(APPROVED_POLICY),
        "reservations": {},
    }


def validate_ledger(payload: object) -> dict[str, Any]:
    """Strictly validate an untrusted ledger loaded from S3."""

    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "created_at",
        "updated_at",
        "policy",
        "reservations",
    }:
        raise FinancialReservationError("financial ledger shape is invalid")
    if payload["schema_version"] != LEDGER_SCHEMA_VERSION:
        raise FinancialReservationError("financial ledger schema version is unsupported")
    _validate_timestamp(payload["created_at"], field="created_at")
    _validate_timestamp(payload["updated_at"], field="updated_at")
    if payload["policy"] != APPROVED_POLICY:
        raise FinancialReservationError("financial ledger policy differs from the approved caps")
    reservations = payload["reservations"]
    if not isinstance(reservations, dict) or len(reservations) > 1_000:
        raise FinancialReservationError("financial ledger reservations are invalid")
    for operation_id, record in reservations.items():
        if not isinstance(operation_id, str) or SHA256_PATTERN.fullmatch(operation_id) is None:
            raise FinancialReservationError("financial ledger operation ID is invalid")
        if not isinstance(record, dict) or set(record) != RECORD_KEYS:
            raise FinancialReservationError("financial ledger reservation record is invalid")
        if record["status"] != "reserved":
            raise FinancialReservationError("financial ledger reservations must remain fail-closed")
        if (
            not isinstance(record["authorization_workflow"], str)
            or WORKFLOW_PATTERN.fullmatch(record["authorization_workflow"]) is None
        ):
            raise FinancialReservationError("financial ledger workflow is invalid")
        if (
            not isinstance(record["authorization_commit_sha"], str)
            or COMMIT_PATTERN.fullmatch(record["authorization_commit_sha"]) is None
        ):
            raise FinancialReservationError("financial ledger commit is invalid")
        for key in (
            "authorization_input_sha256",
            "authorization_reservation_sha256",
            "financial_snapshot_receipt_sha256",
        ):
            if not isinstance(record[key], str) or SHA256_PATTERN.fullmatch(record[key]) is None:
                raise FinancialReservationError("financial ledger digest is invalid")
        _validate_timestamp(record["financial_snapshot_observed_at"], field="observed_at")
        _validate_timestamp(record["reserved_at"], field="reserved_at")
        signed = record["signed_reservation"]
        if not isinstance(signed, dict) or set(signed) != SIGNED_RESERVATION_KEYS:
            raise FinancialReservationError("financial ledger signed reservation is invalid")
        for key, value in signed.items():
            _decimal(value, field=key)
        if _reservation_hash(signed) != record["authorization_reservation_sha256"]:
            raise FinancialReservationError("financial ledger reservation digest is invalid")
    return payload


def _load_ledger_bytes(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinancialReservationError("financial ledger is not canonical JSON") from exc
    checked = validate_ledger(payload)
    if _canonical_json(checked) != raw:
        raise FinancialReservationError("financial ledger is not canonical JSON")
    return checked


def _sum_reserved(
    ledger: Mapping[str, Any],
    field: str,
    *,
    authorization_commit_sha: str,
) -> Decimal:
    return sum(
        (
            _decimal(record["signed_reservation"][field], field=field)
            for record in ledger["reservations"].values()
            if record["authorization_commit_sha"] == authorization_commit_sha
        ),
        Decimal(0),
    )


def reserve_transition(
    ledger: Mapping[str, Any],
    environment: Mapping[str, str],
    *,
    now: datetime,
) -> tuple[dict[str, Any], bool]:
    """Return the next ledger and whether the exact operation was already reserved."""

    checked = validate_ledger(dict(ledger))
    snapshot = build_snapshot(environment, now=now)
    scope = authorization_scope(environment)
    signed = reservation_payload(environment)
    for field in (
        "campaign_budget_usd",
        "required_credit_reserve_usd",
        "maximum_out_of_pocket_usd",
    ):
        if _decimal(signed[field], field=field) != Decimal(APPROVED_POLICY[field]):
            raise FinancialReservationError("signed reservation policy differs from approved caps")

    operation_id = scope["authorization_operation_id"]
    expected_record_identity = {
        "authorization_workflow": scope["authorization_workflow"],
        "authorization_input_sha256": scope["authorization_input_sha256"],
        "authorization_commit_sha": scope["authorization_commit_sha"],
        "authorization_reservation_sha256": scope["authorization_reservation_sha256"],
    }
    existing = checked["reservations"].get(operation_id)
    if existing is not None:
        if any(existing[key] != value for key, value in expected_record_identity.items()):
            raise FinancialReservationError(
                "operation ID is already bound to a different financial reservation"
            )
        return checked, True

    new_usd = _decimal(signed["reservation_max_usd"], field="reservation_max_usd")
    remaining_usd = _decimal(
        signed["reservation_remaining_committed_usd"],
        field="reservation_remaining_committed_usd",
    )
    new_cpu = _decimal(signed["reservation_cpu_hours"], field="reservation_cpu_hours")
    new_gpu = _decimal(signed["reservation_gpu_hours"], field="reservation_gpu_hours")
    spent = _decimal(environment.get(CAMPAIGN_SPEND_ENV), field=CAMPAIGN_SPEND_ENV)
    credit = _decimal(environment.get(REMAINING_CREDIT_ENV), field=REMAINING_CREDIT_ENV)
    current_revision = scope["authorization_commit_sha"]
    reserved_usd = _sum_reserved(
        checked,
        "reservation_max_usd",
        authorization_commit_sha=current_revision,
    )
    reserved_cpu = _sum_reserved(
        checked,
        "reservation_cpu_hours",
        authorization_commit_sha=current_revision,
    )
    reserved_gpu = _sum_reserved(
        checked,
        "reservation_gpu_hours",
        authorization_commit_sha=current_revision,
    )
    cpu_used = _decimal(signed["cpu_hours_used_to_date"], field="cpu_hours_used_to_date")
    gpu_used = _decimal(signed["gpu_hours_used_to_date"], field="gpu_hours_used_to_date")

    total_new_commitment = reserved_usd + new_usd + remaining_usd
    if spent + total_new_commitment > Decimal(APPROVED_POLICY["campaign_budget_usd"]):
        raise FinancialReservationError("reservation would exceed the campaign cap")
    if credit < total_new_commitment + Decimal(APPROVED_POLICY["required_credit_reserve_usd"]):
        raise FinancialReservationError("reservation would consume the required credit reserve")
    if cpu_used + reserved_cpu + new_cpu > Decimal(APPROVED_POLICY["maximum_cpu_hours"]):
        raise FinancialReservationError("reservation would exceed the CPU-hour cap")
    if gpu_used + reserved_gpu + new_gpu > Decimal(APPROVED_POLICY["maximum_gpu_hours"]):
        raise FinancialReservationError("reservation would exceed the GPU-hour cap")

    next_ledger = json.loads(json.dumps(checked))
    next_ledger["updated_at"] = _utc_timestamp(now)
    next_ledger["reservations"][operation_id] = {
        **expected_record_identity,
        "financial_snapshot_observed_at": snapshot.observed_at.isoformat().replace("+00:00", "Z"),
        "financial_snapshot_receipt_sha256": snapshot.receipt_sha256,
        "reserved_at": _utc_timestamp(now),
        "signed_reservation": signed,
        "status": "reserved",
    }
    return validate_ledger(next_ledger), False


def verify_reservation(
    ledger: Mapping[str, Any],
    environment: Mapping[str, str],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Revalidate the snapshot and require its exact immutable reservation record."""

    checked = validate_ledger(dict(ledger))
    build_snapshot(environment, now=now)
    scope = authorization_scope(environment)
    record = checked["reservations"].get(scope["authorization_operation_id"])
    if record is None:
        raise FinancialReservationError("financial capacity was not reserved for this operation")
    for key in (
        "authorization_workflow",
        "authorization_input_sha256",
        "authorization_commit_sha",
        "authorization_reservation_sha256",
    ):
        if record[key] != scope[key]:
            raise FinancialReservationError("financial reservation does not match this operation")
    return checked


def _aws_cli() -> str:
    configured = os.environ.get("REAL_AWS_CLI", "").strip()
    if configured:
        return configured
    discovered = shutil.which("aws")
    if not discovered:
        raise AwsCliError("AWS CLI is unavailable")
    return discovered


def _aws(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [_aws_cli(), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result
    diagnostic = result.stderr + result.stdout
    retryable = any(
        marker in diagnostic
        for marker in ("PreconditionFailed", "ConditionalRequestConflict", "412", "409")
    )
    raise AwsCliError("AWS S3 ledger operation failed", retryable_cas_conflict=retryable)


def _read_remote_ledger(bucket: str, directory: Path) -> tuple[dict[str, Any] | None, str | None]:
    destination = directory / "ledger.json"
    result = subprocess.run(
        [
            _aws_cli(),
            "s3api",
            "get-object",
            "--bucket",
            bucket,
            "--key",
            LEDGER_KEY,
            str(destination),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        diagnostic = result.stderr + result.stdout
        if any(marker in diagnostic for marker in ("NoSuchKey", "Not Found", "404")):
            return None, None
        raise AwsCliError("AWS S3 ledger read failed")
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AwsCliError("AWS S3 ledger metadata is invalid") from exc
    etag = metadata.get("ETag")
    if not isinstance(etag, str) or ETAG_PATTERN.fullmatch(etag) is None:
        raise AwsCliError("AWS S3 ledger ETag is invalid")
    return _load_ledger_bytes(destination.read_bytes()), etag


def _write_remote_ledger(
    bucket: str,
    ledger: Mapping[str, Any],
    directory: Path,
    *,
    etag: str | None,
) -> str:
    source = directory / "next-ledger.json"
    source.write_bytes(_canonical_json(ledger))
    condition = ["--if-none-match", "*"] if etag is None else ["--if-match", etag]
    result = _aws(
        [
            "s3api",
            "put-object",
            "--bucket",
            bucket,
            "--key",
            LEDGER_KEY,
            "--body",
            str(source),
            "--content-type",
            "application/json",
            "--checksum-algorithm",
            "SHA256",
            *condition,
        ]
    )
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AwsCliError("AWS S3 ledger write metadata is invalid") from exc
    new_etag = metadata.get("ETag")
    if not isinstance(new_etag, str) or ETAG_PATTERN.fullmatch(new_etag) is None:
        raise AwsCliError("AWS S3 ledger write ETag is invalid")
    return new_etag


def _proof(environment: Mapping[str, str], *, etag: str, idempotent: bool) -> dict[str, Any]:
    scope = authorization_scope(environment)
    return {
        "schema_version": PROOF_SCHEMA_VERSION,
        "artifact_type": "financial_capacity_reservation",
        **scope,
        "ledger_object_key": LEDGER_KEY,
        "ledger_etag_sha256": "sha256:" + hashlib.sha256(etag.encode("ascii")).hexdigest(),
        "status": "already_reserved" if idempotent else "reserved",
    }


def initialize_remote_ledger(bucket: str, *, now: datetime) -> None:
    for attempt in range(MAXIMUM_CAS_ATTEMPTS):
        with tempfile.TemporaryDirectory(prefix="financial-ledger-") as temporary:
            directory = Path(temporary)
            current, etag = _read_remote_ledger(bucket, directory)
            if current is not None:
                validate_ledger(current)
                return
            try:
                _write_remote_ledger(bucket, empty_ledger(now=now), directory, etag=etag)
                return
            except AwsCliError as exc:
                if not exc.retryable_cas_conflict or attempt + 1 == MAXIMUM_CAS_ATTEMPTS:
                    raise
        time.sleep(0.1 * (attempt + 1))
    raise AwsCliError("AWS S3 ledger initialization exhausted retries")


def reserve_remote(
    bucket: str,
    environment: Mapping[str, str],
    *,
    now: datetime,
) -> dict[str, Any]:
    for attempt in range(MAXIMUM_CAS_ATTEMPTS):
        with tempfile.TemporaryDirectory(prefix="financial-ledger-") as temporary:
            directory = Path(temporary)
            current, etag = _read_remote_ledger(bucket, directory)
            if current is None:
                current = empty_ledger(now=now)
            next_ledger, idempotent = reserve_transition(current, environment, now=now)
            if idempotent and etag is not None:
                return _proof(environment, etag=etag, idempotent=True)
            try:
                new_etag = _write_remote_ledger(
                    bucket,
                    next_ledger,
                    directory,
                    etag=etag,
                )
                return _proof(environment, etag=new_etag, idempotent=False)
            except AwsCliError as exc:
                if not exc.retryable_cas_conflict or attempt + 1 == MAXIMUM_CAS_ATTEMPTS:
                    raise
        time.sleep(0.1 * (attempt + 1))
    raise AwsCliError("AWS S3 ledger reservation exhausted retries")


def verify_remote(
    bucket: str,
    environment: Mapping[str, str],
    *,
    now: datetime,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="financial-ledger-") as temporary:
        current, etag = _read_remote_ledger(bucket, Path(temporary))
    if current is None or etag is None:
        raise FinancialReservationError("financial ledger is unavailable")
    verify_reservation(current, environment, now=now)
    return _proof(environment, etag=etag, idempotent=True)


def _bucket(value: str) -> str:
    if (
        re.fullmatch(
            r"(?=.{3,63}$)(?!.*\.\.)(?!\d+\.\d+\.\d+\.\d+$)[a-z0-9][a-z0-9.-]*[a-z0-9]", value
        )
        is None
    ):
        raise argparse.ArgumentTypeError("state bucket name is invalid")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init")
    initialize.add_argument("--bucket", type=_bucket, required=True)
    reserve = subparsers.add_parser("reserve")
    reserve.add_argument("--bucket", type=_bucket, required=True)
    reserve.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--bucket", type=_bucket, required=True)
    verify.add_argument("--output", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> int:
    args = _parser().parse_args(argv)
    values = os.environ if environment is None else environment
    checked_at = now if now is not None else datetime.now(UTC)
    try:
        if args.command == "init":
            initialize_remote_ledger(args.bucket, now=checked_at)
        elif args.command == "reserve":
            proof = reserve_remote(args.bucket, values, now=checked_at)
            args.output.write_bytes(_canonical_json(proof))
        else:
            proof = verify_remote(args.bucket, values, now=checked_at)
            args.output.write_bytes(_canonical_json(proof))
    except (AwsCliError, FinancialReservationError, FinancialSnapshotError, OSError):
        print(
            "Financial capacity rejected; refresh the signed snapshot or inspect the private "
            "atomic campaign ledger.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
