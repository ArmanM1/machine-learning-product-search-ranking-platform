"""Fail-closed preflight for one bounded SageMaker job; performs no AWS calls."""

from __future__ import annotations

import argparse
import json
from decimal import ROUND_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
HOUR_PRECISION = Decimal("0.0001")


def _amount(value: str, label: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be a decimal number") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{label} must be a finite non-negative amount")
    return amount


def _price_from_aws_json(path: Path) -> Decimal:
    response = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(response, dict):
        raise ValueError("AWS pricing response must be a JSON object")
    prices: list[Decimal] = []
    for encoded in response.get("PriceList", []):
        product: Any = json.loads(encoded) if isinstance(encoded, str) else encoded
        if not isinstance(product, dict):
            continue
        terms = product.get("terms", {}).get("OnDemand", {})
        for term in terms.values():
            for dimension in term.get("priceDimensions", {}).values():
                if dimension.get("unit") in {"Hrs", "Hours"}:
                    price = _amount(
                        str(dimension.get("pricePerUnit", {}).get("USD", "0")),
                        "AWS hourly price",
                    )
                    if price > 0:
                        prices.append(price)
    if not prices:
        raise ValueError("AWS pricing response contained no positive hourly USD price")
    return max(prices)


def estimate(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    if args.runtime_seconds < 1:
        raise ValueError("runtime-seconds must be positive")
    runtime_limits = {
        "development": 4 * 3600,
        "ablation": 4 * 3600,
        "final": 6 * 3600,
        "processing": 4 * 3600,
    }
    maximum_runtime = runtime_limits[args.run_kind]
    errors: list[str] = []
    if args.runtime_seconds > maximum_runtime:
        errors.append(f"runtime exceeds the {maximum_runtime}-second {args.run_kind} job limit")
    if args.run_kind == "processing" and args.accelerator != "cpu":
        errors.append("processing jobs must use the approved CPU path")

    unit_price = (
        _price_from_aws_json(args.pricing_json)
        if args.pricing_json
        else _amount(args.unit_price_usd, "unit-price-usd")
    )
    hours = (Decimal(args.runtime_seconds) / Decimal(3600)).quantize(
        HOUR_PRECISION, rounding=ROUND_UP
    )
    job_estimate = (hours * unit_price).quantize(CENT, rounding=ROUND_UP)
    declared_cap = _amount(args.declared_job_cost_cap_usd, "declared-job-cost-cap-usd")
    spent = _amount(args.campaign_spend_to_date_usd, "campaign-spend-to-date-usd")
    credit = _amount(args.remaining_applicable_credit_usd, "remaining-applicable-credit-usd")
    remaining = _amount(args.estimated_remaining_non_job_usd, "estimated-remaining-non-job-usd")
    campaign_cap = _amount(args.campaign_cap_usd, "campaign-cap-usd")
    reserve = _amount(args.required_credit_reserve_usd, "required-credit-reserve-usd")
    out_of_pocket = _amount(args.maximum_out_of_pocket_usd, "maximum-out-of-pocket-usd")
    used_hours = _amount(args.billed_hours_used_to_date, "billed-hours-used-to-date")

    if out_of_pocket != 0:
        errors.append("owner-approved maximum out-of-pocket exposure is exactly USD 0")
    if job_estimate > declared_cap:
        errors.append("job estimate exceeds the declared per-job cost cap")
    if spent + job_estimate + remaining > campaign_cap:
        errors.append("job would breach the USD 40 pre-credit campaign envelope")
    if credit < job_estimate + remaining + reserve:
        errors.append("credit cannot cover this job, the remaining plan, and required reserve")
    hour_cap = Decimal(20 if args.accelerator == "gpu" else 10)
    if used_hours + hours > hour_cap:
        errors.append(f"job would breach the {hour_cap}-hour {args.accelerator} campaign cap")

    passed = not errors
    result = {
        "schema_version": "1.0.0",
        "status": "passed" if passed else "refused",
        "region": args.region,
        "run_kind": args.run_kind,
        "accelerator": args.accelerator,
        "maximum_runtime_seconds": args.runtime_seconds,
        "maximum_billed_hours": str(hours),
        "hourly_price_upper_bound_usd": str(unit_price),
        "maximum_job_estimate_usd": str(job_estimate),
        "declared_job_cap_usd": str(declared_cap),
        "campaign_envelope_usd": str(campaign_cap),
        "required_credit_reserve_usd": str(reserve),
        "maximum_out_of_pocket_usd": str(out_of_pocket),
        "credit_sufficient": credit >= job_estimate + remaining + reserve,
        "price_source": "aws_price_list_json" if args.pricing_json else "explicit_hourly_input",
        "aws_calls_performed": 0,
        "errors": errors,
    }
    return result, passed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    price = parser.add_mutually_exclusive_group(required=True)
    price.add_argument("--unit-price-usd")
    price.add_argument("--pricing-json", type=Path)
    parser.add_argument(
        "--run-kind",
        required=True,
        choices=("development", "ablation", "final", "processing"),
    )
    parser.add_argument("--accelerator", required=True, choices=("cpu", "gpu"))
    parser.add_argument("--runtime-seconds", required=True, type=int)
    parser.add_argument("--declared-job-cost-cap-usd", required=True)
    parser.add_argument("--campaign-spend-to-date-usd", required=True)
    parser.add_argument("--remaining-applicable-credit-usd", required=True)
    parser.add_argument("--estimated-remaining-non-job-usd", required=True)
    parser.add_argument("--billed-hours-used-to-date", default="0")
    parser.add_argument("--campaign-cap-usd", default="40")
    parser.add_argument("--required-credit-reserve-usd", default="40")
    parser.add_argument("--maximum-out-of-pocket-usd", default="0")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result, passed = estimate(args)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        result, passed = (
            {"status": "refused", "errors": [str(error)], "aws_calls_performed": 0},
            False,
        )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
