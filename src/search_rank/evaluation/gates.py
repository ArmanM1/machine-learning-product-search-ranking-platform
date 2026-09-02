"""Fail-closed held-out and model-promotion gates."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from search_rank.schemas.evaluation import ReleaseGateCheck, ReleaseGateResult

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class HeldoutAccessDenied(RuntimeError):
    """Raised before any held-out data is opened when a guard is incomplete."""


@dataclass(frozen=True)
class HeldoutEvaluationRequest:
    frozen_config_hash: str
    evaluation_config_checksum: str
    candidate_checkpoint_checksum: str
    baseline_model_ids: tuple[str, ...]
    previous_test_access_count: int
    requested_test_access_count: int


@dataclass(frozen=True)
class HeldoutAccessReceipt:
    authorized: bool
    frozen_config_hash: str
    evaluation_config_checksum: str
    candidate_checkpoint_checksum: str
    baseline_model_ids: tuple[str, ...]
    test_access_count: int


def authorize_heldout_evaluation(
    request: HeldoutEvaluationRequest,
    *,
    environ: Mapping[str, str] | None = None,
) -> HeldoutAccessReceipt:
    """Validate every PRD guard without reading the held-out dataset.

    The caller persists ``test_access_count`` transactionally before opening the
    data.  CI and ordinary local runs fail because the environment switch is
    absent.  This function never sets that switch itself.
    """

    environment = os.environ if environ is None else environ
    failures: list[str] = []
    if environment.get("ALLOW_HELDOUT_EVAL") != "1":
        failures.append("ALLOW_HELDOUT_EVAL=1 is required")
    if not _SHA256.fullmatch(request.frozen_config_hash):
        failures.append("a frozen SHA-256 experiment configuration hash is required")
    if not _SHA256.fullmatch(request.evaluation_config_checksum):
        failures.append("a frozen SHA-256 evaluation configuration checksum is required")
    if not _SHA256.fullmatch(request.candidate_checkpoint_checksum):
        failures.append("a SHA-256 candidate checkpoint checksum is required")
    if not request.baseline_model_ids or any(
        not item.strip() for item in request.baseline_model_ids
    ):
        failures.append("at least one declared baseline is required")
    if len(set(request.baseline_model_ids)) != len(request.baseline_model_ids):
        failures.append("declared baselines must be unique")
    if request.previous_test_access_count < 0:
        failures.append("previous test-access count cannot be negative")
    expected_count = request.previous_test_access_count + 1
    if request.requested_test_access_count != expected_count:
        failures.append(
            f"test-access counter must increase monotonically by one (expected {expected_count})"
        )
    if failures:
        raise HeldoutAccessDenied("; ".join(failures))
    return HeldoutAccessReceipt(
        authorized=True,
        frozen_config_hash=request.frozen_config_hash,
        evaluation_config_checksum=request.evaluation_config_checksum,
        candidate_checkpoint_checksum=request.candidate_checkpoint_checksum,
        baseline_model_ids=request.baseline_model_ids,
        test_access_count=request.requested_test_access_count,
    )


@dataclass(frozen=True)
class ReleaseGateConfig:
    relevance_mapping_version: str = "project_graded_v1"
    resampling_unit: str = "query"
    minimum_final_bootstrap_resamples: int = 10_000
    confidence_level: float = 0.95
    reproducibility_tolerance: float = 0.002
    required_clean_runs: int = 2
    maximum_unexplained_slice_regression: float = 0.02
    enforce_slice_regression_gate: bool = True


@dataclass(frozen=True)
class ReleaseGateInputs:
    candidate_model_id: str
    strongest_baseline_model_id: str
    candidate_ndcg_at_10: float
    baseline_ndcg_at_10: float
    difference_ci_lower: float
    difference_ci_upper: float
    confidence_level: float
    relevance_mapping_version: str
    resampling_unit: str
    bootstrap_seed: int | None
    bootstrap_resamples: int
    query_count: int
    excluded_query_count: int | None
    test_access_count: int
    clean_run_metric_values: tuple[float, ...]
    candidate_lists_aligned: bool
    configuration_frozen: bool
    clean_runs_match_artifacts: bool
    unexplained_slice_deltas: tuple[float, ...] = ()


def _check(name: str, passed: bool, detail: str) -> ReleaseGateCheck:
    return ReleaseGateCheck(name=name, passed=passed, detail=detail)


def evaluate_release_gate(
    inputs: ReleaseGateInputs,
    config: ReleaseGateConfig | None = None,
) -> ReleaseGateResult:
    """Apply preregistered gates and retain the baseline on any failure."""

    config = config or ReleaseGateConfig()
    values = (
        inputs.candidate_ndcg_at_10,
        inputs.baseline_ndcg_at_10,
        inputs.difference_ci_lower,
        inputs.difference_ci_upper,
        *inputs.clean_run_metric_values,
        *inputs.unexplained_slice_deltas,
    )
    if any(not isinstance(value, int | float) or isinstance(value, bool) for value in values):
        raise TypeError("release-gate metric values must be numbers")
    if any(value != value or value in (float("inf"), float("-inf")) for value in values):
        raise ValueError("release-gate metric values must be finite")
    if not inputs.candidate_model_id.strip() or not inputs.strongest_baseline_model_id.strip():
        raise ValueError("candidate and baseline model IDs must be non-empty")
    if inputs.candidate_model_id == inputs.strongest_baseline_model_id:
        raise ValueError("candidate and baseline model IDs must differ")

    metric_delta = inputs.candidate_ndcg_at_10 - inputs.baseline_ndcg_at_10
    checks = [
        _check(
            "candidate_improves_primary_metric",
            metric_delta > 0.0,
            f"candidate-minus-baseline graded nDCG@10 = {metric_delta:.12g}; must be > 0",
        ),
        _check(
            "paired_interval_excludes_zero",
            inputs.difference_ci_lower > 0.0
            and inputs.difference_ci_lower <= inputs.difference_ci_upper,
            (
                f"paired CI = [{inputs.difference_ci_lower:.12g}, "
                f"{inputs.difference_ci_upper:.12g}]; lower bound must be > 0"
            ),
        ),
        _check(
            "preregistered_relevance_mapping",
            inputs.relevance_mapping_version == config.relevance_mapping_version,
            f"mapping must be {config.relevance_mapping_version}",
        ),
        _check(
            "query_level_resampling",
            inputs.resampling_unit == config.resampling_unit,
            f"bootstrap unit must be {config.resampling_unit}",
        ),
        _check(
            "confidence_level",
            abs(inputs.confidence_level - config.confidence_level) <= 1e-12,
            f"confidence level must be {config.confidence_level}",
        ),
        _check(
            "final_bootstrap_resamples",
            inputs.bootstrap_resamples >= config.minimum_final_bootstrap_resamples,
            f"final evaluation requires at least {config.minimum_final_bootstrap_resamples} resamples",
        ),
        _check(
            "evaluation_disclosures",
            inputs.query_count > 0
            and inputs.excluded_query_count is not None
            and inputs.excluded_query_count >= 0
            and inputs.bootstrap_seed is not None
            and inputs.bootstrap_seed >= 0
            and inputs.test_access_count >= 1,
            "query/excluded counts, bootstrap seed, and positive test-access count are required",
        ),
        _check(
            "identical_candidate_lists",
            inputs.candidate_lists_aligned,
            "candidate and baseline must rank identical query-product groups",
        ),
        _check(
            "configuration_frozen",
            inputs.configuration_frozen,
            "experiment configuration must be frozen before held-out access",
        ),
    ]

    clean_values = inputs.clean_run_metric_values
    run_count_ok = len(clean_values) >= config.required_clean_runs
    reproducible = (
        run_count_ok and max(clean_values) - min(clean_values) <= config.reproducibility_tolerance
    )
    checks.append(
        _check(
            "clean_run_reproducibility",
            reproducible and inputs.clean_runs_match_artifacts,
            (
                f"requires {config.required_clean_runs} clean runs with absolute spread <= "
                f"{config.reproducibility_tolerance} and matching artifacts/configuration/hardware"
            ),
        )
    )

    if config.enforce_slice_regression_gate:
        largest_regression = min(inputs.unexplained_slice_deltas, default=0.0)
        checks.append(
            _check(
                "major_slice_regression",
                largest_regression >= -config.maximum_unexplained_slice_regression,
                (
                    f"largest unexplained slice delta = {largest_regression:.12g}; "
                    f"must be >= {-config.maximum_unexplained_slice_regression}"
                ),
            )
        )

    passed = all(check.passed for check in checks)
    reasons = [check.detail for check in checks if not check.passed]
    return ReleaseGateResult(
        passed=passed,
        decision="promote_candidate" if passed else "retain_baseline",
        candidate_model_id=inputs.candidate_model_id,
        baseline_model_id=inputs.strongest_baseline_model_id,
        promoted_model_id=(
            inputs.candidate_model_id if passed else inputs.strongest_baseline_model_id
        ),
        positive_claim_allowed=passed,
        negative_result_required=not passed,
        checks=checks,
        reasons=reasons,
    )


apply_release_gate = evaluate_release_gate
decide_promotion = evaluate_release_gate

__all__ = [
    "HeldoutAccessDenied",
    "HeldoutAccessReceipt",
    "HeldoutEvaluationRequest",
    "ReleaseGateConfig",
    "ReleaseGateInputs",
    "apply_release_gate",
    "authorize_heldout_evaluation",
    "decide_promotion",
    "evaluate_release_gate",
]
