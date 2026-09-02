"""End-to-end evaluator over identical per-query candidate universes."""

from __future__ import annotations

import importlib
import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Integral
from pathlib import Path

import pandas as pd
import psutil

from search_rank.baselines.common import ScoredProduct
from search_rank.schemas.evaluation import (
    CostEvidence,
    EvaluationReport,
    ExampleResult,
    MemoryResult,
    MetricResult,
    RuntimeResult,
)

from .bootstrap import paired_bootstrap
from .examples import ExampleCandidate, select_representative_examples
from .gates import ReleaseGateConfig, ReleaseGateInputs, evaluate_release_gate
from .latency import summarize_latency
from .metrics import AggregateMetrics, aggregate_query_metrics, validate_ranking_alignment
from .report import build_primary_metric, select_strongest_baseline, validate_report_consistency
from .slices import CandidateSliceFeatures, assign_predeclared_slices, evaluate_slices


@dataclass(frozen=True)
class EvaluationAlignmentEvidence:
    """Evidence that every system ranked the authoritative candidate universe."""

    candidate_lists_aligned: bool
    authoritative_query_count: int
    authoritative_row_count: int


def _authoritative_labels(frame: pd.DataFrame) -> dict[tuple[str, str], str]:
    required = {"query_id", "product_id", "esci_label"}
    if missing := required - set(frame.columns):
        raise ValueError(f"authoritative evaluation frame missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("authoritative evaluation frame is empty")
    if frame[list(required)].isna().any(axis=None):
        raise ValueError("authoritative evaluation frame contains null query/product/label values")

    labels: dict[tuple[str, str], str] = {}
    for row in frame[["query_id", "product_id", "esci_label"]].itertuples(index=False):
        query_id = str(row.query_id)
        product_id = str(row.product_id)
        label = str(row.esci_label)
        if not query_id or not product_id or not label:
            raise ValueError(
                "authoritative evaluation frame contains empty query/product/label values"
            )
        key = (query_id, product_id)
        if key in labels:
            raise ValueError(
                "authoritative evaluation frame contains duplicate query-product rows: "
                f"{query_id!r}/{product_id!r}"
            )
        labels[key] = label
    return labels


def _validate_system_records(
    records: list[ScoredProduct],
    *,
    expected_model_id: str,
    authoritative_labels: dict[tuple[str, str], str],
) -> dict[str, frozenset[str]]:
    if not records:
        raise ValueError(f"system {expected_model_id!r} has no ranking records")

    observed: dict[tuple[str, str], str] = {}
    ranks: dict[str, list[int]] = defaultdict(list)
    products: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.model_id != expected_model_id:
            raise ValueError(
                f"system {expected_model_id!r} contains record for model {record.model_id!r}"
            )
        if not math.isfinite(float(record.score)):
            raise ValueError(
                f"system {expected_model_id!r} has non-finite score for "
                f"{record.query_id!r}/{record.product_id!r}"
            )
        rank_value: object = record.rank
        if isinstance(rank_value, bool) or not isinstance(rank_value, Integral):
            raise ValueError(f"system {expected_model_id!r} contains a non-integer rank")
        query_id = str(record.query_id)
        product_id = str(record.product_id)
        key = (query_id, product_id)
        if key in observed:
            raise ValueError(
                f"system {expected_model_id!r} contains duplicate query-product record "
                f"{query_id!r}/{product_id!r}"
            )
        observed[key] = str(record.esci_label)
        ranks[query_id].append(int(rank_value))
        products[query_id].add(product_id)

    authoritative_keys = set(authoritative_labels)
    observed_keys = set(observed)
    if observed_keys != authoritative_keys:
        omitted = sorted(authoritative_keys - observed_keys)
        unexpected = sorted(observed_keys - authoritative_keys)
        raise ValueError(
            f"system {expected_model_id!r} does not cover the authoritative frame; "
            f"omitted={omitted[:5]}, unexpected={unexpected[:5]}"
        )
    mismatched_labels = sorted(
        key for key, label in observed.items() if label != authoritative_labels[key]
    )
    if mismatched_labels:
        raise ValueError(
            f"system {expected_model_id!r} labels differ from the authoritative frame for "
            f"{mismatched_labels[:5]}"
        )
    for query_id, query_ranks in ranks.items():
        expected_ranks = list(range(1, len(query_ranks) + 1))
        if sorted(query_ranks) != expected_ranks:
            raise ValueError(
                f"system {expected_model_id!r} ranks for query {query_id!r} must be "
                f"unique and contiguous from 1; observed={sorted(query_ranks)}"
            )
    return {query_id: frozenset(values) for query_id, values in products.items()}


def validate_evaluation_inputs(
    *,
    frame: pd.DataFrame,
    candidate_records: list[ScoredProduct],
    baseline_records: dict[str, list[ScoredProduct]],
    candidate_model_id: str,
) -> EvaluationAlignmentEvidence:
    """Fail closed before metrics if any system diverges from the source frame."""

    if not candidate_model_id:
        raise ValueError("candidate_model_id must be non-empty")
    if not baseline_records:
        raise ValueError("at least one unchanged competitive baseline is required")
    if candidate_model_id in baseline_records:
        raise ValueError("candidate_model_id must be distinct from every baseline model ID")
    if any(not model_id for model_id in baseline_records):
        raise ValueError("baseline model IDs must be non-empty")

    authoritative = _authoritative_labels(frame)
    candidate_products = _validate_system_records(
        candidate_records,
        expected_model_id=candidate_model_id,
        authoritative_labels=authoritative,
    )
    baseline_products = {
        model_id: _validate_system_records(
            records,
            expected_model_id=model_id,
            authoritative_labels=authoritative,
        )
        for model_id, records in baseline_records.items()
    }
    systems_match = all(products == candidate_products for products in baseline_products.values())
    if not systems_match:
        # This should normally be caught by the authoritative-frame checks above,
        # but retain an explicit system-to-system invariant as defense in depth.
        raise ValueError("candidate and baseline candidate lists are not aligned")
    return EvaluationAlignmentEvidence(
        candidate_lists_aligned=systems_match,
        authoritative_query_count=len(candidate_products),
        authoritative_row_count=len(authoritative),
    )


def _peak_resident_memory() -> tuple[float, str]:
    """Read the process high-water mark without labelling a point sample as a peak."""

    info = psutil.Process().memory_info()
    peak_windows = getattr(info, "peak_wset", None)
    if peak_windows is not None:
        return float(peak_windows) / (1024 * 1024), "psutil.memory_info.peak_wset"
    try:
        resource_module = importlib.import_module("resource")
        maximum = float(resource_module.getrusage(resource_module.RUSAGE_SELF).ru_maxrss)
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return maximum / divisor, "resource.getrusage.ru_maxrss"
    except (AttributeError, ImportError, OSError):
        return float(info.rss) / (1024 * 1024), "process_rss_lower_bound; peak unavailable"


def _by_query(records: list[ScoredProduct]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    ordered = sorted(records, key=lambda item: (item.query_id, item.rank, item.product_id))
    labels: dict[str, list[str]] = {}
    products: dict[str, list[str]] = {}
    for record in ordered:
        labels.setdefault(record.query_id, []).append(record.esci_label)
        products.setdefault(record.query_id, []).append(record.product_id)
    return labels, products


def _latency_samples(records: list[ScoredProduct]) -> tuple[list[float], int]:
    per_query: dict[str, float] = {}
    counts: dict[str, int] = {}
    for record in records:
        per_query[record.query_id] = per_query.get(record.query_id, 0.0) + record.latency_ms
        counts[record.query_id] = counts.get(record.query_id, 0) + 1
    candidate_count = max(counts.values(), default=1)
    return list(per_query.values()), candidate_count


def _metric_results(aggregate: AggregateMetrics) -> dict[str, MetricResult]:
    values = aggregate.values
    query_counts = aggregate.metric_query_counts
    excluded_counts = aggregate.metric_excluded_query_counts
    return {
        name: MetricResult(
            metric_name=name,
            value=float(value),
            query_count=query_counts[name],
            excluded_query_count=excluded_counts[name],
        )
        for name, value in values.items()
        if value is not None
    }


def _slice_assignments(frame: pd.DataFrame) -> dict[str, dict[str, str]]:
    assignments: dict[str, dict[str, str]] = {}
    for query_id, group in frame.groupby("query_id", sort=True):
        candidates = [
            CandidateSliceFeatures(
                title=str(row.product_title),
                relevance=str(row.esci_label),
                brand=str(row.product_brand),
                bullet_point=str(row.product_bullet_point),
                description=str(row.product_description),
                product_source=str(row.product_source),
            )
            for row in group.itertuples(index=False)
        ]
        assignments[str(query_id)] = assign_predeclared_slices(
            str(group["query"].iloc[0]), candidates
        )
    return assignments


def _examples(
    candidate_records: list[ScoredProduct],
    baseline_records: list[ScoredProduct],
    candidate_per_query: dict[str, float | None],
    baseline_per_query: dict[str, float | None],
    *,
    baseline_id: str,
) -> list[ExampleResult]:
    baseline_ranks = {(row.query_id, row.product_id): row for row in baseline_records}
    output: list[ExampleCandidate] = []
    for query_id in sorted(candidate_per_query):
        candidate_value = candidate_per_query[query_id]
        baseline_value = baseline_per_query[query_id]
        if candidate_value is None or baseline_value is None:
            continue
        query_candidate = [row for row in candidate_records if row.query_id == query_id]
        complement_exact_confusion = any(
            left.esci_label == "Complement"
            and right.esci_label == "Exact"
            and left.rank < right.rank
            and baseline_ranks[(query_id, left.product_id)].rank
            > baseline_ranks[(query_id, right.product_id)].rank
            for left in query_candidate
            for right in query_candidate
        )
        output.append(
            ExampleCandidate(
                query_id=query_id,
                baseline_metric=float(baseline_value),
                candidate_metric=float(candidate_value),
                public_product_ids=tuple(
                    row.product_id
                    for row in sorted(query_candidate, key=lambda item: item.rank)[:10]
                ),
                lexical_preferred=baseline_id.startswith("bm25")
                and float(candidate_value) < float(baseline_value),
                complement_exact_confusion=complement_exact_confusion,
            )
        )
    return select_representative_examples(output)


def evaluate_systems(
    *,
    frame: pd.DataFrame,
    candidate_records: list[ScoredProduct],
    baseline_records: dict[str, list[ScoredProduct]],
    run_id: str,
    report_id: str,
    candidate_model_id: str,
    split: str,
    test_access_count: int,
    strongest_baseline_id: str | None,
    bootstrap_resamples: int,
    bootstrap_seed: int,
    confidence_level: float,
    training_runtime_seconds: float,
    evaluation_hardware: str,
    model_artifact_size_bytes: int,
    estimated_cost_usd: float = 0.0,
    actual_cost_usd: float | None = None,
    cost_evidence_source: str = "not reconciled; no billing evidence supplied",
    evaluation_started_monotonic: float | None = None,
    slice_min_query_count: int = 30,
    reproduction_tolerance: float = 0.002,
    clean_run_metric_values: tuple[float, ...] = (),
    clean_runs_match_artifacts: bool = False,
    configuration_frozen: bool = False,
    limitations: list[str] | None = None,
) -> EvaluationReport:
    started = evaluation_started_monotonic or time.perf_counter()
    alignment = validate_evaluation_inputs(
        frame=frame,
        candidate_records=candidate_records,
        baseline_records=baseline_records,
        candidate_model_id=candidate_model_id,
    )
    candidate_labels, candidate_products = _by_query(candidate_records)
    baseline_data = {model_id: _by_query(records) for model_id, records in baseline_records.items()}
    for _, products in baseline_data.values():
        validate_ranking_alignment(candidate_products, products)
    candidate_aggregate = aggregate_query_metrics(candidate_labels)
    baseline_aggregates = {
        model_id: aggregate_query_metrics(labels) for model_id, (labels, _) in baseline_data.items()
    }
    baseline_values = {
        model_id: float(result.values["graded_ndcg@10"])
        for model_id, result in baseline_aggregates.items()
        if result.values["graded_ndcg@10"] is not None
    }
    if strongest_baseline_id is None:
        if split == "test":
            raise ValueError("held-out evaluation requires a baseline selected on validation")
        strongest_baseline_id = select_strongest_baseline(baseline_values)[0]
    if strongest_baseline_id not in baseline_aggregates:
        raise ValueError("declared strongest baseline is absent")
    candidate_value = candidate_aggregate.values["graded_ndcg@10"]
    if candidate_value is None:
        raise ValueError("candidate evaluation has no non-degenerate query")
    primary = build_primary_metric(float(candidate_value), baseline_values)
    if primary.strongest_baseline_id != strongest_baseline_id:
        # The frozen validation choice wins on held-out. Rebuild without selecting on test.
        primary = primary.model_copy(
            update={
                "strongest_baseline_id": strongest_baseline_id,
                "strongest_baseline_value": baseline_values[strongest_baseline_id],
                "candidate_minus_baseline": float(candidate_value)
                - baseline_values[strongest_baseline_id],
            }
        )

    paired = []
    intervals = {}
    candidate_per_query = {
        query_id: metrics.graded_ndcg_at_10
        for query_id, metrics in candidate_aggregate.per_query.items()
    }
    for model_id, aggregate in baseline_aggregates.items():
        baseline_per_query = {
            query_id: metrics.graded_ndcg_at_10 for query_id, metrics in aggregate.per_query.items()
        }
        interval = paired_bootstrap(
            candidate_per_query,
            baseline_per_query,
            n_resamples=bootstrap_resamples,
            confidence_level=confidence_level,
            seed=bootstrap_seed,
        )
        intervals[model_id] = interval
        paired.append(
            interval.as_paired_difference(
                metric_name="graded_ndcg@10",
                candidate_model_id=candidate_model_id,
                baseline_model_id=model_id,
            )
        )

    strongest_aggregate = baseline_aggregates[strongest_baseline_id]
    strongest_per_query = {
        query_id: metrics.graded_ndcg_at_10
        for query_id, metrics in strongest_aggregate.per_query.items()
    }
    assignments = _slice_assignments(frame)
    slice_results = evaluate_slices(
        candidate_per_query,
        strongest_per_query,
        assignments,
        n_resamples=bootstrap_resamples,
        confidence_level=confidence_level,
        seed=bootstrap_seed,
        minimum_query_count=slice_min_query_count,
    )
    examples = _examples(
        candidate_records,
        baseline_records[strongest_baseline_id],
        candidate_per_query,
        strongest_per_query,
        baseline_id=strongest_baseline_id,
    )
    primary_interval = intervals[strongest_baseline_id]
    unexplained_regressions = tuple(
        float(result.point_estimate)
        for result in slice_results
        if result.adequate_sample_size
        and result.point_estimate is not None
        and result.point_estimate < 0
    )
    gate = evaluate_release_gate(
        ReleaseGateInputs(
            candidate_model_id=candidate_model_id,
            strongest_baseline_model_id=strongest_baseline_id,
            candidate_ndcg_at_10=float(candidate_value),
            baseline_ndcg_at_10=baseline_values[strongest_baseline_id],
            difference_ci_lower=primary_interval.ci_lower,
            difference_ci_upper=primary_interval.ci_upper,
            confidence_level=confidence_level,
            relevance_mapping_version="project_graded_v1",
            resampling_unit="query",
            bootstrap_seed=bootstrap_seed,
            bootstrap_resamples=bootstrap_resamples,
            query_count=primary_interval.query_count,
            excluded_query_count=primary_interval.excluded_query_count,
            test_access_count=test_access_count,
            clean_run_metric_values=clean_run_metric_values,
            candidate_lists_aligned=alignment.candidate_lists_aligned,
            configuration_frozen=configuration_frozen,
            clean_runs_match_artifacts=clean_runs_match_artifacts,
            unexplained_slice_deltas=unexplained_regressions,
        ),
        ReleaseGateConfig(
            minimum_final_bootstrap_resamples=(10_000 if split == "test" else bootstrap_resamples),
            required_clean_runs=(2 if split == "test" else 1),
            reproducibility_tolerance=reproduction_tolerance,
        ),
    )
    secondary = {}
    for name, value in candidate_aggregate.values.items():
        if name == "graded_ndcg@10" or value is None:
            continue
        secondary[name] = MetricResult(
            metric_name=name,
            value=float(value),
            query_count=candidate_aggregate.metric_query_counts[name],
            excluded_query_count=candidate_aggregate.metric_excluded_query_counts[name],
        )
    system_metrics = {
        candidate_model_id: _metric_results(candidate_aggregate),
        **{
            model_id: _metric_results(aggregate)
            for model_id, aggregate in baseline_aggregates.items()
        },
    }
    latency_results = []
    for model_id, records in {
        candidate_model_id: candidate_records,
        **baseline_records,
    }.items():
        latency_samples, candidate_count = _latency_samples(records)
        latency_results.append(
            summarize_latency(
                latency_samples,
                phase="model_inference",
                candidate_count=candidate_count,
                concurrency=1,
                lambda_memory_mb=None,
                architecture=os.environ.get("PROCESSOR_ARCHITECTURE", "unknown"),
                region=os.environ.get("AWS_REGION", "local"),
                reserved_concurrency=None,
                model_revision=model_id,
            )
        )
    peak_memory_mb, memory_method = _peak_resident_memory()
    report = EvaluationReport(
        schema_version="1.0.0",
        report_id=report_id,
        run_id=run_id,
        candidate_model_id=candidate_model_id,
        baseline_model_ids=list(baseline_records),
        split=split,
        test_access_count=test_access_count,
        query_count=primary_interval.query_count,
        excluded_query_count=primary_interval.excluded_query_count,
        metric_definition_version="project_graded_v1",
        primary_metric=primary,
        secondary_metrics=secondary,
        system_metrics=system_metrics,
        paired_differences=paired,
        bootstrap_method="paired_nonparametric_percentile",
        bootstrap_seed=bootstrap_seed,
        bootstrap_resamples=bootstrap_resamples,
        confidence_level=confidence_level,
        slice_results=slice_results,
        example_results=examples,
        latency_results=latency_results,
        memory_results=MemoryResult(
            peak_resident_memory_mb=peak_memory_mb,
            model_artifact_size_bytes=model_artifact_size_bytes,
            measurement_method=memory_method,
        ),
        training_runtime=RuntimeResult(
            duration_seconds=training_runtime_seconds,
            hardware=evaluation_hardware,
            measured=True,
        ),
        evaluation_runtime=RuntimeResult(
            duration_seconds=time.perf_counter() - started,
            hardware=evaluation_hardware,
            measured=True,
        ),
        cost_evidence=CostEvidence(
            estimated_cost_usd=estimated_cost_usd,
            actual_cost_usd=actual_cost_usd,
            source=cost_evidence_source,
        ),
        release_gate_results=gate,
        limitations=limitations or [],
        created_at=datetime.now(UTC),
    )
    validate_report_consistency(report)
    return report


def write_evaluation_report(report: EvaluationReport, path: str | Path) -> Path:
    validate_report_consistency(report)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output
