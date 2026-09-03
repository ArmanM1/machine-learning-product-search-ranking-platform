from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from scripts.validate_financial_reservation import (
    FinancialReservationCoverageError,
    main,
    validate_reservation_coverage,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _environment(**updates: str) -> dict[str, str]:
    environment = {
        "FINANCIAL_RESERVATION_MAX_USD": "3.00",
        "FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD": "2.00",
        "FINANCIAL_RESERVATION_CPU_HOURS": "4.00",
        "FINANCIAL_RESERVATION_GPU_HOURS": "5.00",
    }
    environment.update(updates)
    return environment


def _validate(environment: dict[str, str]) -> None:
    validate_reservation_coverage(
        environment,
        required_max_usd="3.00",
        required_remaining_committed_usd="2.00",
        required_cpu_hours="4.00",
        required_gpu_hours="5.00",
    )


def test_exact_or_larger_signed_reservation_covers_operation() -> None:
    _validate(_environment())
    _validate(
        _environment(
            FINANCIAL_RESERVATION_MAX_USD="3.01",
            FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD="2.01",
            FINANCIAL_RESERVATION_CPU_HOURS="4.01",
            FINANCIAL_RESERVATION_GPU_HOURS="5.01",
        )
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("FINANCIAL_RESERVATION_MAX_USD", "2.99"),
        ("FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD", "1.99"),
        ("FINANCIAL_RESERVATION_CPU_HOURS", "3.99"),
        ("FINANCIAL_RESERVATION_GPU_HOURS", "4.99"),
    ),
)
def test_each_under_sized_reservation_field_fails_closed(field: str, value: str) -> None:
    with pytest.raises(FinancialReservationCoverageError, match=field):
        _validate(_environment(**{field: value}))


@pytest.mark.parametrize(
    "value",
    ("", "not-a-number", "NaN", "Infinity", "-0.01"),
)
def test_invalid_reservation_amount_fails_closed(value: str) -> None:
    with pytest.raises(FinancialReservationCoverageError):
        _validate(_environment(FINANCIAL_RESERVATION_MAX_USD=value))


@pytest.mark.parametrize(
    "field",
    (
        "FINANCIAL_RESERVATION_MAX_USD",
        "FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD",
        "FINANCIAL_RESERVATION_CPU_HOURS",
        "FINANCIAL_RESERVATION_GPU_HOURS",
    ),
)
def test_missing_reservation_amount_fails_closed(field: str) -> None:
    environment = _environment()
    del environment[field]
    with pytest.raises(FinancialReservationCoverageError, match=field):
        _validate(environment)


def test_cli_error_does_not_echo_the_protected_value(capsys: pytest.CaptureFixture[str]) -> None:
    protected_value = "0.123456789-sensitive"
    result = main(
        (
            "--required-max-usd",
            "3.00",
            "--required-remaining-committed-usd",
            "2.00",
            "--required-cpu-hours",
            "4.00",
            "--required-gpu-hours",
            "5.00",
        ),
        environment=_environment(FINANCIAL_RESERVATION_MAX_USD=protected_value),
    )
    captured = capsys.readouterr()
    assert result == 1
    assert protected_value not in captured.err


def test_workflow_guards_bind_the_exact_allowance_dimensions_before_reservation() -> None:
    expected_bindings = {
        ("baseline.yml", "baseline"): (
            'allowance = amount("BASELINE_RUN_ALLOWANCE_USD")',
            "required_max_usd=allowance",
            "required_remaining_committed_usd=0",
            "required_cpu_hours=0",
            "required_gpu_hours=0",
        ),
        ("benchmark-serving.yml", "benchmark"): (
            'allowance = amount("BENCHMARK_COST_ALLOWANCE_USD")',
            "required_max_usd=allowance",
            "required_remaining_committed_usd=0",
            "required_cpu_hours=0",
            "required_gpu_hours=0",
        ),
        ("bootstrap-baseline.yml", "publish"): (
            'allowance = amount("BASELINE_PUBLICATION_ALLOWANCE_USD")',
            "required_max_usd=allowance",
            "required_remaining_committed_usd=0",
            "required_cpu_hours=0",
            "required_gpu_hours=0",
        ),
        ("build-images.yml", "build-and-push"): (
            'allowance = Decimal("1.00")',
            "required_max_usd=allowance",
            "required_remaining_committed_usd=0",
            "required_cpu_hours=0",
            "required_gpu_hours=0",
        ),
        ("deploy.yml", "deploy"): (
            'conservative_serving_allowance = Decimal("3.00")',
            "required_max_usd=conservative_serving_allowance",
            "required_remaining_committed_usd=0",
            "required_cpu_hours=0",
            "required_gpu_hours=0",
        ),
        ("deploy.yml", "rollback"): (
            'rollback_allowance = Decimal("0.10")',
            "required_max_usd=rollback_allowance",
            "required_remaining_committed_usd=0",
            "required_cpu_hours=0",
            "required_gpu_hours=0",
        ),
        ("freeze-trial-selection.yml", "freeze"): (
            'allowance = amount("VALIDATION_BINDING_ALLOWANCE_USD")',
            "required_max_usd=allowance",
            "required_remaining_committed_usd=0",
            "required_cpu_hours=0",
            "required_gpu_hours=0",
        ),
        ("infrastructure.yml", "terraform"): (
            'required_max_usd="0"',
            'required_max_usd="3.00"',
            '--required-max-usd "${required_max_usd}"',
            "--required-remaining-committed-usd 0",
            "--required-cpu-hours 0",
            "--required-gpu-hours 0",
        ),
        ("prepare-data.yml", "prepare-and-publish"): (
            'allowance = amount("DATA_PUBLICATION_ALLOWANCE_USD")',
            "required_max_usd=allowance",
            "required_remaining_committed_usd=0",
            "required_cpu_hours=0",
            "required_gpu_hours=0",
        ),
        ("release.yml", "evaluate-and-promote"): (
            "required_max_usd=estimate",
            "required_remaining_committed_usd=remaining",
            "required_cpu_hours=total_hours",
            "required_gpu_hours=0",
        ),
        ("train.yml", "submit"): (
            "required_max_usd=estimate",
            "required_remaining_committed_usd=remaining",
            'required_cpu_hours=hours if accelerator == "cpu" else 0',
            'required_gpu_hours=hours if accelerator == "gpu" else 0',
        ),
    }

    for (workflow_name, job_name), snippets in expected_bindings.items():
        payload = yaml.safe_load((WORKFLOWS / workflow_name).read_text(encoding="utf-8"))
        steps = payload["jobs"][job_name]["steps"]
        reservation_position = next(
            index
            for index, step in enumerate(steps)
            if step.get("name") == "Atomically reserve the signed campaign capacity"
        )
        pre_reservation_commands = "\n".join(
            step.get("run", "") for step in steps[:reservation_position]
        )
        for snippet in snippets:
            assert snippet in pre_reservation_commands, (workflow_name, job_name, snippet)


def test_infrastructure_reservation_is_zero_for_plan_and_matches_the_apply_allowance() -> None:
    payload = yaml.safe_load((WORKFLOWS / "infrastructure.yml").read_text(encoding="utf-8"))
    steps = payload["jobs"]["terraform"]["steps"]
    cost_guard = next(
        step["run"]
        for step in steps
        if step.get("name") == "Validate authorization and zero-out-of-pocket boundary"
    )
    reservation_guard = next(
        step["run"]
        for step in steps
        if step.get("name") == "Bind the signed reservation to the infrastructure allowance"
    )
    allowance_match = re.search(r'bootstrap_allowance = Decimal\("([0-9.]+)"\)', cost_guard)
    assert allowance_match is not None
    apply_allowance = allowance_match.group(1)

    assert (
        'required_max_usd="0"\n'
        'if [[ "${OPERATION}" == "apply" ]]; then\n'
        f'  required_max_usd="{apply_allowance}"\n'
        "fi"
    ) in reservation_guard
    assert '--required-max-usd "${required_max_usd}"' in reservation_guard
