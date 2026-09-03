#!/usr/bin/env python3
"""Fail closed unless a signed campaign reservation covers an operation."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

RESERVATION_FIELDS = {
    "maximum USD": "FINANCIAL_RESERVATION_MAX_USD",
    "remaining committed USD": "FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD",
    "CPU hours": "FINANCIAL_RESERVATION_CPU_HOURS",
    "GPU hours": "FINANCIAL_RESERVATION_GPU_HOURS",
}


class FinancialReservationCoverageError(ValueError):
    """A protected reservation is missing, invalid, or too small."""


def _amount(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise FinancialReservationCoverageError(f"{field} must be a decimal amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FinancialReservationCoverageError(f"{field} must be a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise FinancialReservationCoverageError(f"{field} must be finite and non-negative")
    return amount


def validate_reservation_coverage(
    environment: Mapping[str, str],
    *,
    required_max_usd: object,
    required_remaining_committed_usd: object,
    required_cpu_hours: object,
    required_gpu_hours: object,
) -> None:
    """Require each signed reservation field to cover its operation requirement."""

    requirements = {
        "maximum USD": required_max_usd,
        "remaining committed USD": required_remaining_committed_usd,
        "CPU hours": required_cpu_hours,
        "GPU hours": required_gpu_hours,
    }
    for label, environment_name in RESERVATION_FIELDS.items():
        reserved = _amount(environment.get(environment_name), field=environment_name)
        required = _amount(requirements[label], field=f"required {label}")
        if reserved < required:
            raise FinancialReservationCoverageError(
                f"{environment_name} does not cover the required {label}"
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--required-max-usd", required=True)
    parser.add_argument("--required-remaining-committed-usd", required=True)
    parser.add_argument("--required-cpu-hours", required=True)
    parser.add_argument("--required-gpu-hours", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    values = os.environ if environment is None else environment
    try:
        validate_reservation_coverage(
            values,
            required_max_usd=args.required_max_usd,
            required_remaining_committed_usd=args.required_remaining_committed_usd,
            required_cpu_hours=args.required_cpu_hours,
            required_gpu_hours=args.required_gpu_hours,
        )
    except FinancialReservationCoverageError as error:
        print(f"Financial reservation rejected: {error}", file=sys.stderr)
        return 1
    print("Signed financial reservation covers the operation requirements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
