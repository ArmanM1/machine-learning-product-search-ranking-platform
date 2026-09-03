from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from scripts import reserve_financial_capacity, validate_financial_snapshot

NOW = datetime(2026, 9, 2, 18, 0, tzinfo=UTC)


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "FINANCIAL_SNAPSHOT_OBSERVED_AT": (NOW - timedelta(minutes=1)).isoformat(),
        "FINANCIAL_SNAPSHOT_HMAC_KEY": "4" * 64,
        "FINANCIAL_SNAPSHOT_SOURCE": "aws_billing_and_cost_management_console",
        "FINANCIAL_SNAPSHOT_MAX_AGE_SECONDS": "21600",
        "CAMPAIGN_SPEND_TO_DATE_USD": "0",
        "REMAINING_APPLICABLE_CREDIT_USD": "100",
        "FINANCIAL_SNAPSHOT_AUTHORIZATION_WORKFLOW": "train",
        "FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON": '{"authorization":"GO","run":"one"}',
        "FINANCIAL_SNAPSHOT_AUTHORIZATION_COMMIT_SHA": "a" * 40,
        "FINANCIAL_RESERVATION_MAX_USD": "3",
        "FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD": "0",
        "FINANCIAL_RESERVATION_CPU_HOURS": "2",
        "FINANCIAL_RESERVATION_GPU_HOURS": "0",
        "FINANCIAL_CPU_HOURS_USED_TO_DATE": "0",
        "FINANCIAL_GPU_HOURS_USED_TO_DATE": "0",
        "CAMPAIGN_BUDGET_USD": "40",
        "REQUIRED_CREDIT_RESERVE_USD": "40",
        "MAXIMUM_OUT_OF_POCKET_USD": "0",
    }
    values.update(overrides)
    values["FINANCIAL_SNAPSHOT_RECEIPT_SHA256"] = (
        validate_financial_snapshot.compute_receipt_sha256(values)
    )
    return values


def test_new_reservation_consumes_the_shared_envelope_without_exposing_balances() -> None:
    environment = _environment()
    ledger, idempotent = reserve_financial_capacity.reserve_transition(
        reserve_financial_capacity.empty_ledger(now=NOW),
        environment,
        now=NOW,
    )

    assert idempotent is False
    operation_id = validate_financial_snapshot.authorization_scope(environment)[
        "authorization_operation_id"
    ]
    assert ledger["reservations"][operation_id]["status"] == "reserved"
    assert (
        Decimal(ledger["reservations"][operation_id]["signed_reservation"]["reservation_max_usd"])
        == 3
    )
    serialized = reserve_financial_capacity._canonical_json(ledger).decode("utf-8")
    assert "100" not in serialized


def test_exact_same_operation_is_idempotent() -> None:
    environment = _environment()
    ledger, _ = reserve_financial_capacity.reserve_transition(
        reserve_financial_capacity.empty_ledger(now=NOW), environment, now=NOW
    )

    same, idempotent = reserve_financial_capacity.reserve_transition(
        ledger, environment, now=NOW + timedelta(seconds=1)
    )

    assert idempotent is True
    assert same == ledger


def test_same_operation_with_changed_reservation_is_rejected() -> None:
    environment = _environment()
    ledger, _ = reserve_financial_capacity.reserve_transition(
        reserve_financial_capacity.empty_ledger(now=NOW), environment, now=NOW
    )
    changed = _environment(FINANCIAL_RESERVATION_MAX_USD="4")

    with pytest.raises(
        reserve_financial_capacity.FinancialReservationError,
        match="already bound",
    ):
        reserve_financial_capacity.reserve_transition(
            ledger, changed, now=NOW + timedelta(seconds=1)
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"CAMPAIGN_SPEND_TO_DATE_USD": "39", "FINANCIAL_RESERVATION_MAX_USD": "2"},
            "campaign cap",
        ),
        (
            {"REMAINING_APPLICABLE_CREDIT_USD": "42", "FINANCIAL_RESERVATION_MAX_USD": "3"},
            "credit reserve",
        ),
        (
            {"FINANCIAL_CPU_HOURS_USED_TO_DATE": "9", "FINANCIAL_RESERVATION_CPU_HOURS": "2"},
            "CPU-hour cap",
        ),
        (
            {"FINANCIAL_GPU_HOURS_USED_TO_DATE": "19", "FINANCIAL_RESERVATION_GPU_HOURS": "2"},
            "GPU-hour cap",
        ),
    ],
)
def test_reservation_rejects_each_aggregate_cap(overrides: dict[str, str], message: str) -> None:
    environment = _environment(**overrides)

    with pytest.raises(reserve_financial_capacity.FinancialReservationError, match=message):
        reserve_financial_capacity.reserve_transition(
            reserve_financial_capacity.empty_ledger(now=NOW), environment, now=NOW
        )


def test_existing_reservations_are_counted_against_later_operations() -> None:
    first = _environment(FINANCIAL_RESERVATION_CPU_HOURS="6")
    ledger, _ = reserve_financial_capacity.reserve_transition(
        reserve_financial_capacity.empty_ledger(now=NOW), first, now=NOW
    )
    second = _environment(
        FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON='{"authorization":"GO","run":"two"}',
        FINANCIAL_RESERVATION_CPU_HOURS="5",
    )

    with pytest.raises(
        reserve_financial_capacity.FinancialReservationError,
        match="CPU-hour cap",
    ):
        reserve_financial_capacity.reserve_transition(
            ledger, second, now=NOW + timedelta(seconds=1)
        )


@pytest.mark.parametrize(
    ("reservation_field", "first_value", "second_value", "message"),
    (
        ("FINANCIAL_RESERVATION_MAX_USD", "20", "21", "campaign cap"),
        ("FINANCIAL_RESERVATION_CPU_HOURS", "6", "5", "CPU-hour cap"),
        ("FINANCIAL_RESERVATION_GPU_HOURS", "12", "9", "GPU-hour cap"),
    ),
)
def test_same_revision_reservations_aggregate_against_every_cap(
    reservation_field: str,
    first_value: str,
    second_value: str,
    message: str,
) -> None:
    first = _environment(**{reservation_field: first_value})
    ledger, _ = reserve_financial_capacity.reserve_transition(
        reserve_financial_capacity.empty_ledger(now=NOW), first, now=NOW
    )
    second = _environment(
        **{
            "FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON": ('{"authorization":"GO","run":"two"}'),
            reservation_field: second_value,
        }
    )

    with pytest.raises(reserve_financial_capacity.FinancialReservationError, match=message):
        reserve_financial_capacity.reserve_transition(
            ledger,
            second,
            now=NOW + timedelta(seconds=1),
        )


def test_prior_revision_reservations_remain_auditable_without_consuming_new_totals() -> None:
    first = _environment(
        FINANCIAL_RESERVATION_MAX_USD="39",
        FINANCIAL_RESERVATION_CPU_HOURS="9",
        FINANCIAL_RESERVATION_GPU_HOURS="19",
    )
    ledger, _ = reserve_financial_capacity.reserve_transition(
        reserve_financial_capacity.empty_ledger(now=NOW), first, now=NOW
    )
    first_operation = validate_financial_snapshot.authorization_scope(first)[
        "authorization_operation_id"
    ]
    first_record = copy.deepcopy(ledger["reservations"][first_operation])
    second = _environment(
        FINANCIAL_SNAPSHOT_AUTHORIZATION_COMMIT_SHA="b" * 40,
        FINANCIAL_RESERVATION_MAX_USD="39",
        FINANCIAL_RESERVATION_CPU_HOURS="9",
        FINANCIAL_RESERVATION_GPU_HOURS="19",
    )

    updated, idempotent = reserve_financial_capacity.reserve_transition(
        ledger,
        second,
        now=NOW + timedelta(seconds=1),
    )

    assert idempotent is False
    assert len(updated["reservations"]) == 2
    assert updated["reservations"][first_operation] == first_record
    assert (
        reserve_financial_capacity.verify_reservation(
            updated,
            first,
            now=NOW + timedelta(seconds=2),
        )
        == updated
    )
    assert (
        reserve_financial_capacity.verify_reservation(
            updated,
            second,
            now=NOW + timedelta(seconds=2),
        )
        == updated
    )


def test_verify_requires_an_exact_reserved_operation() -> None:
    environment = _environment()
    empty = reserve_financial_capacity.empty_ledger(now=NOW)

    with pytest.raises(
        reserve_financial_capacity.FinancialReservationError,
        match="not reserved",
    ):
        reserve_financial_capacity.verify_reservation(empty, environment, now=NOW)


def test_ledger_rejects_tampering_and_noncanonical_bytes() -> None:
    environment = _environment()
    ledger, _ = reserve_financial_capacity.reserve_transition(
        reserve_financial_capacity.empty_ledger(now=NOW), environment, now=NOW
    )
    operation_id = next(iter(ledger["reservations"]))
    tampered = copy.deepcopy(ledger)
    tampered["reservations"][operation_id]["signed_reservation"]["reservation_max_usd"] = "1"

    with pytest.raises(
        reserve_financial_capacity.FinancialReservationError,
        match="digest",
    ):
        reserve_financial_capacity.validate_ledger(tampered)
    with pytest.raises(
        reserve_financial_capacity.FinancialReservationError,
        match="canonical",
    ):
        reserve_financial_capacity._load_ledger_bytes(
            reserve_financial_capacity._canonical_json(ledger) + b"\n"
        )


def test_aws_conditional_write_uses_exact_fixed_key_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    calls: list[list[str]] = []

    class Result:
        stdout = json.dumps({"ETag": '"0123456789abcdef0123456789abcdef"'})

    def fake_aws(args):
        calls.append(list(args))
        return Result()

    monkeypatch.setattr(reserve_financial_capacity, "_aws", fake_aws)
    etag = '"fedcba9876543210fedcba9876543210"'

    reserve_financial_capacity._write_remote_ledger(
        "approved-state-bucket",
        reserve_financial_capacity.empty_ledger(now=NOW),
        tmp_path,
        etag=etag,
    )

    assert calls[0][:6] == [
        "s3api",
        "put-object",
        "--bucket",
        "approved-state-bucket",
        "--key",
        "cost-control/ledger.json",
    ]
    assert calls[0][-2:] == ["--if-match", etag]


def test_aws_initial_create_uses_if_none_match(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[list[str]] = []

    class Result:
        stdout = json.dumps({"ETag": '"0123456789abcdef0123456789abcdef"'})

    def fake_aws(args):
        calls.append(list(args))
        return Result()

    monkeypatch.setattr(reserve_financial_capacity, "_aws", fake_aws)
    reserve_financial_capacity._write_remote_ledger(
        "approved-state-bucket",
        reserve_financial_capacity.empty_ledger(now=NOW),
        tmp_path,
        etag=None,
    )

    assert calls[0][-2:] == ["--if-none-match", "*"]
