"""Stable command-line interface for reproducible ranking workflows."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, cast

import pandas as pd
import typer
import uvicorn
from pydantic import ValidationError
from sentence_transformers import CrossEncoder

from search_rank.artifacts import sha256_directory, sha256_file
from search_rank.baselines import (
    bm25_model_id,
    rank_bm25,
    rank_cross_encoder,
    rank_input_order,
    rank_seeded_random,
)
from search_rank.baselines.common import ScoredProduct, read_rankings, write_rankings
from search_rank.baselines.cross_encoder import assert_parameters_unchanged, load_unchanged_model
from search_rank.command_config import BaselineRunConfig, EvaluationRunConfig
from search_rank.config import sha256_value, validate_config
from search_rank.data import load_data_config
from search_rank.data.io import load_dataset_manifest, load_prepared_split
from search_rank.data.prepare import prepare_dataset
from search_rank.evaluation.gates import (
    HeldoutAccessReceipt,
    HeldoutEvaluationRequest,
    ReleaseGateConfig,
    ReleaseGateInputs,
    authorize_heldout_evaluation,
    evaluate_release_gate,
)
from search_rank.evaluation.latency import summarize_latency
from search_rank.evaluation.metrics import AggregateMetrics, aggregate_query_metrics
from search_rank.evaluation.report import select_strongest_baseline
from search_rank.evaluation.runner import (
    evaluate_systems,
    validate_evaluation_inputs,
    write_evaluation_report,
)
from search_rank.logging import configure_logging, log_event
from search_rank.runs import CommandRun
from search_rank.schemas.api import (
    ModelSummary,
    PublicEvaluationProvenance,
    PublicModelMetricRow,
    PublicRunSummary,
    PublicTrainingProvenance,
    PublicValidationRunMetrics,
    PublicValidationRunSummary,
)
from search_rank.schemas.evaluation import EvaluationReport, PairedDifference, ReleaseGateResult
from search_rank.schemas.evidence import BundleChecksums, EvaluationProvenance, ReleaseManifest
from search_rank.schemas.model import ModelArtifact
from search_rank.schemas.publication import BaselineSummary, CommandSummary
from search_rank.schemas.run import RunManifest
from search_rank.schemas.trial import TrialSelection
from search_rank.serving.app import create_app
from search_rank.serving.dependencies import ServiceSettings, ServiceState
from search_rank.serving.public_evidence import (
    build_public_evidence,
    build_validation_public_evidence,
    public_run_intervals,
    public_run_metrics,
    write_public_evidence,
)
from search_rank.serving.query_store import (
    CuratedProduct,
    CuratedQuery,
    EscIRelevance,
    QueryStore,
    write_curated_queries,
)
from search_rank.training import (
    build_mixed_sample,
    freeze_experiment_config,
    load_frozen_experiment,
    mine_hard_examples,
    train_candidate,
)

LOGGER = logging.getLogger(__name__)
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
PUBLIC_DISTRIBUTION_NOTICES = ("LICENSE", "NOTICE")
app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
data_app = typer.Typer(no_args_is_help=True)
baseline_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(baseline_app, name="baseline")


def _abort(run: CommandRun, error: Exception) -> NoReturn:
    message = str(error) or type(error).__name__
    summary = run.finish(status="failed", failure=message)
    log_event(LOGGER, "command_failed", run_id=run.run_id, reason=message)
    typer.echo(json.dumps({"run_id": run.run_id, "status": "failed", "summary": str(summary)}))
    raise typer.Exit(code=1)


def _success(run: CommandRun, result: dict[str, Any]) -> None:
    summary = run.finish(status="succeeded", result=result)
    log_event(LOGGER, "command_succeeded", run_id=run.run_id, summary=str(summary))
    typer.echo(json.dumps({"run_id": run.run_id, "status": "succeeded", "summary": str(summary)}))


def _read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _copy_public_distribution_notices(destination: Path) -> tuple[Path, ...]:
    """Copy the repository license and third-party attribution into a public bundle."""

    candidates = (
        Path.cwd(),
        Path(__file__).resolve().parents[2],
        Path("/var/task"),
    )
    source_root = next(
        (
            candidate
            for candidate in candidates
            if all((candidate / name).is_file() for name in PUBLIC_DISTRIBUTION_NOTICES)
        ),
        None,
    )
    if source_root is None:
        raise FileNotFoundError("public distribution LICENSE and NOTICE files are unavailable")
    return tuple(
        Path(shutil.copy2(source_root / name, destination / name))
        for name in PUBLIC_DISTRIBUTION_NOTICES
    )


def _write_bundle_checksums(root: Path) -> Path:
    output = root / "bundle-checksums.json"
    files = {
        path.relative_to(root).as_posix(): f"sha256:{sha256_file(path)}"
        for path in sorted(root.rglob("*"))
        if path.is_file() and path != output
    }
    inventory = BundleChecksums.model_validate({"schema_version": "1.0.0", "files": files})
    output.write_text(inventory.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output


def _verify_bundle_checksum_inventory(root: Path) -> None:
    bundle_path = root / "bundle-checksums.json"
    inventory = BundleChecksums.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    files = inventory.files
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != bundle_path
    }
    if set(files) != actual:
        raise ValueError("bundle checksum inventory does not exactly match release files")
    for relative, expected in files.items():
        path = (root / str(relative)).resolve()
        resolved_root = root.resolve()
        if (
            path == resolved_root
            or resolved_root not in path.parents
            or not path.is_file()
            or not SHA256_PATTERN.fullmatch(str(expected))
            or str(expected) != f"sha256:{sha256_file(path)}"
        ):
            raise ValueError(f"bundle checksum verification failed: {relative}")


def _latest_summary(pointer: str | Path) -> dict[str, Any]:
    value = _read_json(pointer)
    if "summary" in value:
        return _read_json(str(value["summary"]))
    return value


def _pretrained_id(path: Path) -> str:
    payload = _read_yaml(path)
    return f"pretrained-cross-encoder@{payload['revision']}"


def _read_yaml(path: Path) -> dict[str, Any]:
    from search_rank.config import load_yaml

    return load_yaml(path)


def _snapshot(model: CrossEncoder) -> dict[str, Any]:
    if model.model is None:
        raise RuntimeError("cross-encoder has no underlying model")
    return {
        name: tensor.detach().cpu().clone() for name, tensor in model.model.state_dict().items()
    }


def _run_baselines(
    frame: pd.DataFrame,
    config: BaselineRunConfig,
) -> dict[str, list[ScoredProduct]]:
    rankings: dict[str, list[ScoredProduct]] = {}
    if "input_order" in config.systems:
        values = rank_input_order(frame)
        rankings[values[0].model_id] = values
    if "seeded_random" in config.systems:
        values = rank_seeded_random(frame, seed=config.random_seed)
        rankings[values[0].model_id] = values
    if "bm25" in config.systems:
        for template in config.input_templates:
            text_column = "text_title_v1" if template == "title_v1" else "text_enriched_v1"
            values = rank_bm25(
                frame,
                text_column=text_column,
                k1=config.bm25.k1,
                b=config.bm25.b,
            )
            rankings[values[0].model_id] = values
    if "pretrained_cross_encoder" in config.systems:
        model = load_unchanged_model(
            config.cross_encoder.model_config_path,
            device=config.cross_encoder.device,
        )
        before = _snapshot(model)
        for template in config.input_templates:
            text_column = "text_title_v1" if template == "title_v1" else "text_enriched_v1"
            model_id = f"{_pretrained_id(config.cross_encoder.model_config_path)}-{template}"
            rankings[model_id] = rank_cross_encoder(
                frame,
                model=model,
                model_id=model_id,
                text_column=text_column,
                batch_size=config.cross_encoder.batch_size,
            )
        assert_parameters_unchanged(model, before)
    if not rankings:
        raise ValueError("baseline configuration selected no systems")
    return rankings


def _metric(records: list[ScoredProduct]) -> float:
    labels: dict[str, list[str]] = {}
    for row in sorted(records, key=lambda item: (item.query_id, item.rank, item.product_id)):
        labels.setdefault(row.query_id, []).append(row.esci_label)
    value = aggregate_query_metrics(labels).values["graded_ndcg@10"]
    if value is None:
        raise ValueError("ranking contains no evaluable query")
    return float(value)


def _aggregate_records(records: list[ScoredProduct]) -> AggregateMetrics:
    labels: dict[str, list[str]] = {}
    for row in sorted(records, key=lambda item: (item.query_id, item.rank, item.product_id)):
        labels.setdefault(row.query_id, []).append(row.esci_label)
    return aggregate_query_metrics(labels)


def _p95_inference_latency(records: list[ScoredProduct]) -> float:
    per_query: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in records:
        per_query[row.query_id] = per_query.get(row.query_id, 0.0) + row.latency_ms
        counts[row.query_id] = counts.get(row.query_id, 0) + 1
    return summarize_latency(
        list(per_query.values()),
        phase="model_inference",
        candidate_count=max(counts.values(), default=1),
        concurrency=1,
        lambda_memory_mb=None,
        architecture=os.environ.get("PROCESSOR_ARCHITECTURE", "unknown"),
        region=os.environ.get("AWS_REGION", "local"),
        reserved_concurrency=None,
        model_revision=records[0].model_id,
    ).p95_ms


def _ranking_hash(records: list[ScoredProduct], *, include_scores: bool) -> str:
    ordered = sorted(records, key=lambda item: (item.query_id, item.rank, item.product_id))
    rows = (
        [(row.query_id, row.product_id, row.rank, round(row.score, 12)) for row in ordered]
        if include_scores
        else [(row.query_id, row.product_id, row.rank) for row in ordered]
    )
    return f"sha256:{sha256_value(rows)}"


def _candidate_universe_hash(records: list[ScoredProduct]) -> str:
    """Bind identical query/product membership without conflating it with model order."""

    rows = sorted((row.query_id, row.product_id) for row in records)
    if len(rows) != len(set(rows)):
        raise ValueError("candidate universe contains a duplicate query/product pair")
    return f"sha256:{sha256_value(rows)}"


def _competitive(rankings: dict[str, list[ScoredProduct]]) -> dict[str, float]:
    values = {
        model_id: _metric(records)
        for model_id, records in rankings.items()
        if model_id.startswith("bm25-") or model_id.startswith("pretrained-cross-encoder@")
    }
    return values or {model_id: _metric(records) for model_id, records in rankings.items()}


def _expected_baseline_ids(config: BaselineRunConfig) -> set[str]:
    expected: set[str] = set()
    if "input_order" in config.systems:
        expected.add("input-order-v1")
    if "seeded_random" in config.systems:
        expected.add(f"seeded-random-v1-seed-{config.random_seed}")
    for template in config.input_templates:
        text_column = "text_title_v1" if template == "title_v1" else "text_enriched_v1"
        if "bm25" in config.systems:
            expected.add(
                bm25_model_id(
                    text_column=text_column,
                    k1=config.bm25.k1,
                    b=config.bm25.b,
                )
            )
        if "pretrained_cross_encoder" in config.systems:
            expected.add(f"{_pretrained_id(config.cross_encoder.model_config_path)}-{template}")
    return expected


def _resume_baseline_rankings(
    summary_path: Path,
    *,
    config_path: Path,
    config: BaselineRunConfig,
    frame: pd.DataFrame,
) -> tuple[dict[str, list[ScoredProduct]], str]:
    """Recover fully-written, checksummed rankings after report-only failure."""

    summary = _read_json(summary_path)
    if summary.get("command") != "baseline-run" or summary.get("status") != "failed":
        raise ValueError("--resume-from requires a failed baseline-run summary")
    recorded_config = Path(str(summary.get("config_path", ""))).resolve()
    if recorded_config != config_path.resolve():
        raise ValueError("resumed baseline configuration path differs from the failed run")
    paths = summary.get("artifact_paths")
    hashes = summary.get("artifact_hashes")
    if not isinstance(paths, dict) or not isinstance(hashes, dict):
        raise ValueError("failed baseline summary has no artifact inventory")
    ranking_names = sorted(name for name in paths if str(name).startswith("ranking_"))
    expected_ids = _expected_baseline_ids(config)
    if len(ranking_names) != len(expected_ids) or set(ranking_names) != {
        f"ranking_{index:02d}" for index in range(len(expected_ids))
    }:
        raise ValueError("failed baseline summary does not contain every expected ranking")

    rankings: dict[str, list[ScoredProduct]] = {}
    authoritative = {
        (str(row.query_id), str(row.product_id)): (str(row.query), int(row.source_index))
        for row in frame.itertuples(index=False)
    }
    for name in ranking_names:
        ranking_path = Path(str(paths[name]))
        if not ranking_path.is_file():
            ranking_path = summary_path.resolve().parent / "rankings" / f"{name[-2:]}.jsonl"
        expected_hash = str(hashes.get(name, ""))
        if (
            not ranking_path.is_file()
            or not SHA256_PATTERN.fullmatch(expected_hash)
            or expected_hash != f"sha256:{sha256_file(ranking_path)}"
        ):
            raise ValueError(f"resumed baseline ranking checksum mismatch: {name}")
        try:
            records = [ScoredProduct(**row) for row in read_rankings(ranking_path)]
        except (TypeError, ValueError) as error:
            raise ValueError(f"resumed baseline ranking is invalid: {name}") from error
        model_ids = {record.model_id for record in records}
        if len(model_ids) != 1:
            raise ValueError(f"resumed ranking mixes model identities: {name}")
        model_id = next(iter(model_ids))
        if model_id in rankings:
            raise ValueError(f"resumed baseline model is duplicated: {model_id}")
        for record in records:
            if not math.isfinite(record.latency_ms) or record.latency_ms < 0:
                raise ValueError(f"resumed baseline has invalid latency: {model_id}")
            identity = authoritative.get((record.query_id, record.product_id))
            if identity != (record.query, record.source_index):
                raise ValueError(f"resumed baseline row differs from prepared data: {model_id}")
        rankings[model_id] = records
    if set(rankings) != expected_ids:
        raise ValueError("resumed baseline model set differs from the supplied configuration")
    ordered_ids = sorted(rankings)
    validate_evaluation_inputs(
        frame=frame,
        candidate_records=rankings[ordered_ids[0]],
        baseline_records={model_id: rankings[model_id] for model_id in ordered_ids[1:]},
        candidate_model_id=ordered_ids[0],
    )
    return rankings, str(summary["run_id"])


@data_app.command("prepare")
def data_prepare(
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Acquire, verify, normalize, split, and checksum the ESCI data."""

    configure_logging()
    run = CommandRun("data-prepare", str(config))
    try:
        validated = load_data_config(config)
        manifest, destination = prepare_dataset(validated)
        for name in ("manifest.json", "data-quality.json", "artifact-checksums.json"):
            run.add_artifact(name, destination / name)
        _success(
            run,
            {
                "dataset_manifest": str((destination / "manifest.json").resolve()),
                "processed_checksum": manifest.processed_checksum,
                "split_manifest_hash": manifest.split_manifest_hash,
                "query_count": manifest.query_count,
                "row_count": manifest.row_count,
            },
        )
    except (OSError, ValueError, ValidationError) as error:
        _abort(run, error)


@baseline_app.command("run")
def baseline_run(
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    resume_from: Annotated[
        Path | None,
        typer.Option("--resume-from", exists=True, dir_okay=False, readable=True),
    ] = None,
) -> None:
    """Run deterministic controls and unchanged competitive baselines."""

    configure_logging()
    run = CommandRun("baseline-run", str(config))
    try:
        validated = validate_config(config, BaselineRunConfig)
        frame, manifest = load_prepared_split(validated.dataset_manifest, validated.split)
        resumed_from_run_id: str | None = None
        if resume_from is None:
            rankings = _run_baselines(frame, validated)
        else:
            rankings, resumed_from_run_id = _resume_baseline_rankings(
                resume_from,
                config_path=config,
                config=validated,
                frame=frame,
            )
        ranking_paths: dict[str, str] = {}
        for index, (model_id, records) in enumerate(sorted(rankings.items())):
            path = run.run_dir / "rankings" / f"{index:02d}.jsonl"
            write_rankings(path, records)
            run.add_artifact(f"ranking_{index:02d}", path)
            ranking_paths[model_id] = str(path.resolve())
        metrics = _competitive(rankings)
        strongest_id, strongest_value = select_strongest_baseline(metrics)
        aggregates = {
            model_id: _aggregate_records(records) for model_id, records in rankings.items()
        }
        config_hash = f"sha256:{sha256_value(validated)}"
        selected_aggregate = aggregates[strongest_id]
        baseline_summary = run.run_dir / "baseline-summary.json"
        baseline_summary.parent.mkdir(parents=True, exist_ok=True)
        baseline_artifact = BaselineSummary.model_validate(
            {
                "schema_version": "1.0.0",
                "config_hash": config_hash,
                "dataset_manifest_hash": manifest.processed_checksum,
                "dataset_name": manifest.dataset_name,
                "dataset_version": manifest.dataset_version,
                "dataset_locale": manifest.locale,
                "split": validated.split,
                "metrics": metrics,
                "system_metrics": {
                    model_id: {
                        name: value for name, value in aggregate.values.items() if value is not None
                    }
                    for model_id, aggregate in aggregates.items()
                },
                "system_metric_query_counts": {
                    model_id: dict(aggregate.metric_query_counts)
                    for model_id, aggregate in aggregates.items()
                },
                "system_metric_excluded_query_counts": {
                    model_id: dict(aggregate.metric_excluded_query_counts)
                    for model_id, aggregate in aggregates.items()
                },
                "p95_inference_latency_ms": {
                    model_id: _p95_inference_latency(records)
                    for model_id, records in rankings.items()
                },
                "strongest_baseline_id": strongest_id,
                "strongest_baseline_value": strongest_value,
                "validation_query_count": manifest.split_counts[validated.split].query_count,
                "excluded_query_count": selected_aggregate.metric_excluded_query_counts[
                    "graded_ndcg@10"
                ],
                "rankings": ranking_paths,
                "resumed_from_run_id": resumed_from_run_id,
            }
        )
        baseline_summary.write_text(
            baseline_artifact.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        run.add_artifact("baseline_summary", baseline_summary)
        curated_path = write_curated_queries(run.run_dir / "curated-queries.json", _curated(frame))
        run.add_artifact("curated_queries", curated_path)
        _success(
            run,
            {
                "dataset_checksum": manifest.processed_checksum,
                "config_hash": config_hash,
                "baseline_summary": str(baseline_summary.resolve()),
                "curated_queries": str(curated_path.resolve()),
                "strongest_baseline_id": strongest_id,
                "metrics": metrics,
                "resumed_from_run_id": resumed_from_run_id,
            },
        )
    except (OSError, ValueError, ValidationError, RuntimeError) as error:
        _abort(run, error)


@app.command("bootstrap-baseline-release")
def bootstrap_baseline_release(
    baseline_summary: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    baseline_config: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    dataset_manifest: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    curated_queries: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    output_dir: Annotated[Path, typer.Option(file_okay=False)],
    image_digest: Annotated[str, typer.Option()],
    git_sha: Annotated[str, typer.Option()],
    hardware_class: Annotated[str, typer.Option()],
    region: Annotated[str, typer.Option()] = "us-east-1",
) -> None:
    """Build an immutable validation-only baseline release with zero test access."""

    configure_logging()
    run = CommandRun("bootstrap-baseline-release", str(baseline_config))
    try:
        if not SHA256_PATTERN.fullmatch(image_digest):
            raise ValueError("--image-digest must be a canonical sha256 digest")
        if not GIT_SHA_PATTERN.fullmatch(git_sha):
            raise ValueError("--git-sha must be a hexadecimal commit revision")
        if not hardware_class.strip() or not region.strip():
            raise ValueError("hardware class and region must be non-empty")
        if output_dir.exists():
            raise FileExistsError(f"immutable baseline release already exists: {output_dir}")

        summary = _latest_summary(baseline_summary)
        if summary.get("command") != "baseline-run" or summary.get("status") != "succeeded":
            raise ValueError("baseline release requires a successful baseline-run summary")
        result = summary.get("result")
        hashes = summary.get("artifact_hashes")
        if not isinstance(result, dict) or not isinstance(hashes, dict):
            raise ValueError("baseline command summary is missing result or artifact hashes")
        artifact_path = Path(str(result.get("baseline_summary", "")))
        if not artifact_path.is_file():
            artifact_path = baseline_summary.resolve().parent / "baseline-summary.json"
        if str(hashes.get("baseline_summary", "")) != f"sha256:{sha256_file(artifact_path)}":
            raise ValueError("baseline artifact differs from its successful command summary")
        if str(hashes.get("curated_queries", "")) != f"sha256:{sha256_file(curated_queries)}":
            raise ValueError("curated queries differ from the baseline command evidence")

        baseline_artifact = BaselineSummary.model_validate_json(
            artifact_path.read_text(encoding="utf-8")
        )
        artifact = baseline_artifact.model_dump(mode="json")
        validated_config = validate_config(baseline_config, BaselineRunConfig)
        config_hash = f"sha256:{sha256_value(validated_config)}"
        if artifact.get("config_hash") != config_hash:
            raise ValueError("baseline artifact differs from the supplied baseline config")
        manifest, _ = load_dataset_manifest(dataset_manifest)
        if artifact.get("dataset_manifest_hash") != manifest.processed_checksum:
            raise ValueError("baseline artifact differs from the supplied dataset identity")

        query_store = QueryStore.from_json(curated_queries)
        candidate_counts = {len(query.products) for query in query_store.search(limit=50)}
        if not {10, 20, 40} <= candidate_counts:
            raise ValueError(
                "baseline release requires curated query variants of size 10, 20, and 40"
            )

        selected_id = str(artifact["strongest_baseline_id"])
        metrics_value = artifact.get("system_metrics")
        metric_counts_value = artifact.get("system_metric_query_counts")
        metric_excluded_value = artifact.get("system_metric_excluded_query_counts")
        latencies_value = artifact.get("p95_inference_latency_ms")
        if not all(
            isinstance(value, dict)
            for value in (
                metrics_value,
                metric_counts_value,
                metric_excluded_value,
                latencies_value,
            )
        ):
            raise ValueError("baseline artifact lacks typed per-system validation evidence")
        metrics = cast(dict[str, dict[str, float]], metrics_value)
        latencies = cast(dict[str, float], latencies_value)

        output_parent = output_dir.resolve().parent
        output_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-staging-", dir=output_parent))
        pretrained_checksum: str | None = None
        pretrained_relative: str | None = None
        competitive_ids = sorted(
            model_id
            for model_id in metrics
            if model_id.startswith("bm25-") or model_id.startswith("pretrained-cross-encoder@")
        )
        if selected_id not in competitive_ids:
            raise ValueError("selected baseline is absent from competitive validation systems")
        if any(model_id.startswith("pretrained-cross-encoder@") for model_id in competitive_ids):
            pretrained_dir = staging / "models" / "pretrained"
            unchanged = load_unchanged_model(
                validated_config.cross_encoder.model_config_path, device="cpu"
            )
            unchanged.save_pretrained(
                str(pretrained_dir), create_model_card=False, safe_serialization=True
            )
            pretrained_checksum = f"sha256:{sha256_directory(pretrained_dir)}"
            pretrained_relative = "models/pretrained"

        evidence_id = f"validation-{summary['run_id']}"
        promoted_at = datetime.now(UTC)
        public_models: list[PublicModelMetricRow] = []
        release_models: list[dict[str, Any]] = []
        model_config = _read_yaml(validated_config.cross_encoder.model_config_path)
        for model_id in competitive_ids:
            kind: Literal["bm25", "pretrained"] = (
                "bm25" if model_id.startswith("bm25-") else "pretrained"
            )
            checksum = (
                f"sha256:{sha256_value({'model_id': model_id})}"
                if kind == "bm25"
                else pretrained_checksum
            )
            if checksum is None:
                raise ValueError("pretrained baseline checkpoint was not materialized")
            template = (
                "title_v1"
                if model_id.endswith("-title_v1") or "-text_title_v1-" in model_id
                else "enriched_v1"
            )
            values = metrics[model_id]
            if not isinstance(values, dict) or "graded_ndcg@10" not in values:
                raise ValueError(f"baseline system lacks graded nDCG@10: {model_id}")
            public_models.append(
                PublicModelMetricRow(
                    model_id=model_id,
                    display_name=(
                        "BM25 lexical baseline"
                        if kind == "bm25"
                        else "Unchanged pretrained cross-encoder"
                    ),
                    kind=kind,
                    graded_ndcg_at_10=float(values["graded_ndcg@10"]),
                    exact_mrr_at_10=values.get("exact_mrr@10"),
                    recall_exact_or_substitute_at_10=values.get("recall_exact_or_substitute@10"),
                    pairwise_ordinal_accuracy=values.get("pairwise_ordinal_accuracy"),
                    graded_ndcg_at_5=values.get("graded_ndcg@5"),
                    exact_top_1_rate=values.get("exact_top_1_rate"),
                    p95_inference_latency_ms=float(latencies[model_id]),
                )
            )
            model_summary = ModelSummary(
                model_id=model_id,
                display_name=(
                    "BM25 lexical baseline"
                    if kind == "bm25"
                    else "Unchanged pretrained cross-encoder"
                ),
                kind=kind,
                base_model_id=(str(model_config["model_id"]) if kind == "pretrained" else None),
                artifact_checksum=checksum,
                evaluation_report_id=evidence_id,
                promoted_at=promoted_at if model_id == selected_id else None,
                limitations_url="/methodology#limitations",
            )
            release_model: dict[str, Any] = {
                "model_id": model_id,
                "kind": kind,
                "text_template": template,
                "artifact_checksum": checksum,
                "public_summary": model_summary.model_dump(mode="json"),
            }
            if kind == "pretrained":
                release_model.update({"checkpoint": pretrained_relative, "batch_size": 32})
            release_models.append(release_model)

        selected_metric = float(metrics[selected_id]["graded_ndcg@10"])
        run_summary = PublicValidationRunSummary(
            run_id=str(summary["run_id"]),
            selected_model_id=selected_id,
            config_hash=config_hash,
            dataset_manifest_hash=manifest.processed_checksum,
            split_manifest_hash=manifest.split_manifest_hash,
            git_sha=git_sha,
            image_digest=image_digest,
            model_artifact_checksum=next(
                str(model["artifact_checksum"])
                for model in release_models
                if model["model_id"] == selected_id
            ),
            dataset_name=manifest.dataset_name,
            dataset_version=manifest.dataset_version,
            locale="us",
            base_model_id=(
                str(model_config["model_id"])
                if selected_id.startswith("pretrained-cross-encoder@")
                else None
            ),
            hardware_class=hardware_class,
            region=region,
            metrics=PublicValidationRunMetrics(selected_model_graded_ndcg_at_10=selected_metric),
            duration_seconds=float(summary.get("duration_seconds", 0.0)),
            actual_cost_usd=None,
            cost_evidence="No cloud billing record is attached to validation-only evidence.",
            validation_only_notice=(
                "Baseline selected on validation before any held-out evaluation."
            ),
            limitations=[
                "This bootstrap release contains validation evidence only.",
                "The system reranks supplied candidates and is not full-catalog retrieval.",
            ],
            prohibited_claims=[
                "No held-out improvement claim is allowed.",
                "No shopper, conversion, or production-scale impact is claimed.",
            ],
            reproduction_command=(
                "python -m search_rank.cli baseline run --config "
                "configs/experiments/baselines-v1.yaml"
            ),
        )
        evidence = build_validation_public_evidence(
            run_summary,
            evidence_id=evidence_id,
            validation_query_count=int(artifact["validation_query_count"]),
            excluded_query_count=int(artifact["excluded_query_count"]),
            models=public_models,
            selection_note=(
                "Strongest unchanged competitive baseline selected by validation graded nDCG@10."
            ),
            failure_analysis_reason=(
                "Held-out failure analysis is not performed for the validation-only bootstrap."
            ),
        )
        shutil.copy2(artifact_path, staging / "baseline-summary.json")
        shutil.copy2(curated_queries, staging / "curated-queries.json")
        evidence_path = write_public_evidence(evidence, staging / "public-evidence.json")
        _copy_public_distribution_notices(staging)
        artifact_checksums = {
            "baseline-summary.json": f"sha256:{sha256_file(staging / 'baseline-summary.json')}",
            "curated-queries.json": f"sha256:{sha256_file(staging / 'curated-queries.json')}",
            "public-evidence.json": f"sha256:{sha256_file(evidence_path)}",
            "LICENSE": f"sha256:{sha256_file(staging / 'LICENSE')}",
            "NOTICE": f"sha256:{sha256_file(staging / 'NOTICE')}",
        }
        release_id = f"baseline-{summary['run_id']}"
        release_manifest = ReleaseManifest.model_validate(
            {
                "schema_version": "1.0.0",
                "release_id": release_id,
                "promoted_model_id": selected_id,
                "dataset_manifest_hash": manifest.processed_checksum,
                "split_manifest_hash": manifest.split_manifest_hash,
                "evaluation_report_id": evidence_id,
                "git_sha": git_sha,
                "evidence_mode": "validation_only",
                "artifact_checksums": artifact_checksums,
                "models": release_models,
            }
        )
        release_manifest_payload = release_manifest.model_dump(mode="json", exclude_none=True)
        release_manifest_path = staging / "release-manifest.json"
        release_manifest_path.write_text(
            json.dumps(release_manifest_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        ServiceState._validate_evidence_binding(evidence, release_manifest_payload)
        _write_bundle_checksums(staging)
        _verify_bundle_checksum_inventory(staging)
        os.replace(staging, output_dir.resolve())
        run.add_artifact("release_manifest", output_dir / "release-manifest.json")
        run.add_artifact("public_evidence", output_dir / "public-evidence.json")
        run.add_artifact("bundle_checksums", output_dir / "bundle-checksums.json")
        _success(
            run,
            {
                "release_id": release_id,
                "release_dir": str(output_dir.resolve()),
                "release_manifest": str((output_dir / "release-manifest.json").resolve()),
                "public_evidence": str((output_dir / "public-evidence.json").resolve()),
                "bundle_checksums": str((output_dir / "bundle-checksums.json").resolve()),
                "promoted_model_id": selected_id,
                "evidence_mode": "validation_only",
                "split_manifest_hash": manifest.split_manifest_hash,
                "test_access_count": 0,
            },
        )
    except (OSError, KeyError, TypeError, ValueError, ValidationError, RuntimeError) as error:
        _abort(run, error)


@app.command("freeze-config")
def freeze_config(
    template: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    dataset_manifest: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Option(dir_okay=False)],
) -> None:
    """Materialize and hash a candidate experiment before held-out access."""

    configure_logging()
    run = CommandRun("freeze-config", str(template))
    try:
        frozen = freeze_experiment_config(
            template,
            dataset_manifest_path=dataset_manifest,
            output_path=output,
        )
        run.add_artifact("frozen_config", output)
        run.add_artifact("frozen_config_json", output.with_suffix(output.suffix + ".json"))
        _success(run, {"config_hash": frozen.config_hash, "output": str(output.resolve())})
    except (OSError, ValueError, ValidationError) as error:
        _abort(run, error)


@app.command("train")
def train(
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    dataset_manifest: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, readable=True)
    ] = Path("data/processed/esci-us-v1/current.json"),
) -> None:
    """Fine-tune one frozen candidate configuration using training data only."""

    configure_logging()
    run = CommandRun("train", str(config))
    try:
        experiment = load_frozen_experiment(config)
        cloud_hardware = os.environ.get("SEARCH_RANK_HARDWARE_CLASS")
        declared_accelerator = os.environ.get("SEARCH_RANK_ACCELERATOR")
        training_device = "auto"
        if cloud_hardware is not None or declared_accelerator is not None:
            if cloud_hardware is None or declared_accelerator is None:
                raise ValueError(
                    "cloud hardware and accelerator declarations must be provided together"
                )
            if experiment.requested_hardware != cloud_hardware:
                raise ValueError(
                    "frozen experiment requested_hardware differs from the runtime instance"
                )
            expected_accelerator = {
                "ml.m5.xlarge": "cpu",
                "ml.g4dn.xlarge": "gpu",
            }.get(cloud_hardware)
            if expected_accelerator is None or declared_accelerator != expected_accelerator:
                raise ValueError("runtime instance and accelerator declarations are inconsistent")
            training_device = "cuda" if declared_accelerator == "gpu" else "cpu"
        manifest, _ = load_dataset_manifest(dataset_manifest)
        manifest_hash = manifest.processed_checksum
        if manifest_hash != experiment.dataset_manifest_hash:
            raise ValueError("frozen experiment references a different dataset manifest")
        training_frame, _ = load_prepared_split(dataset_manifest, "train")
        validation_frame, _ = load_prepared_split(dataset_manifest, "validation")
        text_column = (
            "text_title_v1"
            if experiment.input_template_version == "title_v1"
            else "text_enriched_v1"
        )
        mining_records: list[ScoredProduct] = []
        if "bm25" in experiment.hard_example_sources:
            mining_records.extend(rank_bm25(training_frame, text_column=text_column))
        if "pretrained_cross_encoder" in experiment.hard_example_sources:
            unchanged = CrossEncoder(
                experiment.base_model_id,
                revision=experiment.base_model_revision,
                trust_remote_code=False,
                max_length=experiment.max_sequence_length,
                num_labels=1,
            )
            mining_records.extend(
                rank_cross_encoder(
                    training_frame,
                    model=unchanged,
                    model_id=(
                        f"pretrained-cross-encoder@{experiment.base_model_revision}-"
                        f"{experiment.input_template_version}"
                    ),
                    text_column=text_column,
                )
            )
        hard = (
            mine_hard_examples(training_frame, mining_records)
            if mining_records
            else pd.DataFrame(
                columns=[
                    "query_id",
                    "lower_product_id",
                    "higher_product_id",
                    "lower_grade",
                    "higher_grade",
                    "grade_difference",
                    "source_baseline",
                    "score_margin",
                ]
            )
        )
        hard_fraction = 0.0 if experiment.sampling_strategy == "random_only_v1" else 0.5
        sample = build_mixed_sample(
            training_frame,
            hard,
            hard_fraction=hard_fraction,
            seed=experiment.seed,
            text_column=text_column,
        )
        sampling_counts = {
            str(key): int(value)
            for key, value in sample["sampling_source"].value_counts().sort_index().items()
        }
        label_counts = {
            str(key): int(value)
            for key, value in sample["esci_label"].value_counts().sort_index().items()
        }
        run.run_dir.mkdir(parents=True, exist_ok=True)
        hard_path = run.run_dir / "hard-examples.parquet"
        sample_path = run.run_dir / "training-sample.parquet"
        hard.to_parquet(hard_path, index=False)
        sample.to_parquet(sample_path, index=False)
        result = train_candidate(
            sample,
            validation_frame,
            experiment,
            output_dir=run.run_dir / "candidate",
            device=training_device,
            checkpoint_dir=os.environ.get("SEARCH_RANK_CHECKPOINT_DIR"),
        )
        if declared_accelerator is not None and result.accelerator_type != declared_accelerator:
            raise RuntimeError("actual training accelerator differs from the frozen cloud request")
        frozen_copy = run.run_dir / "candidate" / "frozen-experiment.yaml"
        shutil.copy2(config, frozen_copy)
        candidate_id = f"candidate-{experiment.config_id}-{experiment.config_hash[7:19]}"
        checkpoint_checksum = f"sha256:{sha256_directory(result.best_checkpoint)}"
        checkpoint_size_bytes = sum(
            path.stat().st_size
            for path in Path(result.best_checkpoint).rglob("*")
            if path.is_file()
        )
        artifact = ModelArtifact.model_validate(
            {
                "schema_version": "1.0.0",
                "model_id": candidate_id,
                "run_id": os.environ.get("SEARCH_RANK_CLOUD_RUN_ID", run.run_id),
                "base_model_id": experiment.base_model_id,
                "base_model_revision": experiment.base_model_revision,
                "tokenizer_revision": experiment.base_model_revision,
                "checkpoint_uri": "candidate/best",
                "artifact_checksum": checkpoint_checksum,
                "artifact_size_bytes": checkpoint_size_bytes,
                "config_id": experiment.config_id,
                "config_hash": experiment.config_hash,
                "dataset_manifest_hash": manifest_hash,
                "input_contract_version": experiment.input_template_version,
                "label_mapping_version": experiment.label_mapping_version,
                "sampling_strategy": experiment.sampling_strategy,
                "hard_example_sources": experiment.hard_example_sources,
                "promoted": False,
                "promotion_reason": "pending held-out evaluation",
                "evaluation_report_id": "not_evaluated",
                "git_sha": os.environ.get("SEARCH_RANK_GIT_SHA", "unavailable"),
                "image_digest": os.environ.get("SEARCH_RANK_TRAINING_IMAGE_DIGEST", "unavailable"),
                "sample_statistics": {
                    "row_count": len(sample),
                    "sampling_source_counts": sampling_counts,
                    "label_counts": label_counts,
                },
                "training_result": {
                    **result.__dict__,
                    "best_checkpoint": "candidate/best",
                    "curves_path": "candidate/curves.json",
                },
                "created_at": datetime.now(UTC),
            }
        )
        model_manifest = run.run_dir / "model-manifest.json"
        model_manifest.write_text(
            artifact.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        for name, path in {
            "hard_examples": hard_path,
            "training_sample": sample_path,
            "model_manifest": model_manifest,
            "training_curves": Path(result.curves_path),
            "frozen_config": frozen_copy,
        }.items():
            run.add_artifact(name, path)
        _success(
            run,
            {
                "candidate_model_id": candidate_id,
                "checkpoint": result.best_checkpoint,
                "checkpoint_checksum": checkpoint_checksum,
                "config_hash": experiment.config_hash,
                "dataset_manifest_hash": manifest_hash,
                "best_validation_ndcg_at_10": result.best_validation_ndcg_at_10,
                "duration_seconds": result.duration_seconds,
                "hardware_class": cloud_hardware or "local-cpu",
                "accelerator": result.accelerator_type,
                "device_type": result.device_type,
                "cuda_available": result.cuda_available,
                "cuda_device_count": result.cuda_device_count,
                "training_image_digest": os.environ.get(
                    "SEARCH_RANK_TRAINING_IMAGE_DIGEST", "sha256:" + "0" * 64
                ),
                "region": os.environ.get("AWS_REGION", "local"),
                "input_template_version": experiment.input_template_version,
                "frozen_config": str(frozen_copy.resolve()),
                "sample_statistics": {
                    "row_count": len(sample),
                    "sampling_source_counts": sampling_counts,
                    "label_counts": label_counts,
                },
            },
        )
    except (OSError, ValueError, ValidationError, RuntimeError, AssertionError) as error:
        _abort(run, error)


def _heldout_receipt(
    *,
    heldout: bool,
    split: str,
    config_hash: str,
    evaluation_config_checksum: str,
    checkpoint_checksum: str,
    baselines: tuple[str, ...],
) -> HeldoutAccessReceipt | None:
    if split != "test":
        if heldout:
            raise ValueError("--heldout is valid only with a test evaluation configuration")
        return None
    if not heldout:
        raise ValueError("test evaluation requires the explicit --heldout flag")
    counter_path = Path("artifacts/heldout-access.json")
    prior = _read_json(counter_path).get("test_access_count", 0) if counter_path.exists() else 0
    receipt = authorize_heldout_evaluation(
        HeldoutEvaluationRequest(
            frozen_config_hash=config_hash,
            evaluation_config_checksum=evaluation_config_checksum,
            candidate_checkpoint_checksum=checkpoint_checksum,
            baseline_model_ids=baselines,
            previous_test_access_count=int(prior),
            requested_test_access_count=int(prior) + 1,
        )
    )
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    counter_path.write_text(
        json.dumps(
            {
                "test_access_count": receipt.test_access_count,
                "frozen_config_hash": receipt.frozen_config_hash,
                "evaluation_config_checksum": receipt.evaluation_config_checksum,
                "candidate_checkpoint_checksum": receipt.candidate_checkpoint_checksum,
                "baseline_model_ids": list(receipt.baseline_model_ids),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt


def _esci_label(value: object) -> EscIRelevance:
    label = str(value)
    if label not in {"Exact", "Substitute", "Complement", "Irrelevant"}:
        raise ValueError(f"unknown ESCI label in curated evidence: {label}")
    return label  # type: ignore[return-value]


def _curated(
    frame: pd.DataFrame,
    limit: int = 12,
    *,
    required_query_ids: tuple[str, ...] = (),
) -> list[CuratedQuery]:
    queries: list[CuratedQuery] = []
    grouped = {str(query_id): group for query_id, group in frame.groupby("query_id", sort=True)}

    benchmark = next(
        ((query_id, group) for query_id, group in grouped.items() if len(group) >= 40),
        None,
    )
    if benchmark is None:
        raise ValueError("curated evidence requires one query with at least 40 candidates")

    def build(query_id: str, group: pd.DataFrame, count: int) -> CuratedQuery:
        candidates = tuple(
            CuratedProduct(
                product_id=str(row.product_id),
                title=str(row.product_title) or "Untitled product",
                text=str(row.text_enriched_v1),
                esci_label=_esci_label(row.esci_label),
            )
            for row in group.head(count).itertuples(index=False)
        )
        return CuratedQuery(
            query_id=query_id,
            query=str(group["query"].iloc[0]),
            products=candidates,
        )

    benchmark_id, benchmark_group = benchmark
    for count in (10, 20, 40):
        queries.append(build(f"{benchmark_id}-benchmark-{count}", benchmark_group, count))

    ordered_ids = [
        *dict.fromkeys(required_query_ids),
        *(query_id for query_id in grouped if query_id not in required_query_ids),
    ]
    for query_id in ordered_ids:
        if len(queries) >= limit and query_id not in required_query_ids:
            break
        group = grouped.get(query_id)
        if group is None:
            raise ValueError(f"required curated query is missing from evaluation: {query_id}")
        queries.append(build(query_id, group, min(len(group), 40)))
    return queries


@app.command("evaluate")
def evaluate(
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    heldout: Annotated[bool, typer.Option("--heldout")] = False,
) -> None:
    """Evaluate identical candidate universes; held-out access is fail-closed."""

    configure_logging()
    evaluation_started = time.perf_counter()
    run = CommandRun("evaluate", str(config))
    try:
        staged_evaluation_checksum = f"sha256:{sha256_file(config)}"
        expected_staged = os.environ.get("SEARCH_RANK_STAGED_EVALUATION_CONFIG_SHA256")
        if expected_staged and expected_staged != staged_evaluation_checksum:
            raise ValueError("staged evaluation configuration checksum mismatch")
        frozen_evaluation_checksum = os.environ.get("SEARCH_RANK_FROZEN_EVALUATION_CONFIG_SHA256")
        if heldout and not frozen_evaluation_checksum:
            raise ValueError(
                "held-out evaluation requires a container-verified frozen evaluation checksum"
            )
        frozen_evaluation_checksum = frozen_evaluation_checksum or staged_evaluation_checksum
        evaluation_image_digest = os.environ.get("SEARCH_RANK_EVALUATION_IMAGE_DIGEST")
        evaluation_git_sha = os.environ.get("SEARCH_RANK_GIT_SHA")
        hardware_class = os.environ.get("SEARCH_RANK_HARDWARE_CLASS", "local-cpu")
        evaluation_region = os.environ.get("AWS_REGION", "local")
        if heldout and not (
            evaluation_image_digest
            and SHA256_PATTERN.fullmatch(evaluation_image_digest)
            and evaluation_git_sha
            and GIT_SHA_PATTERN.fullmatch(evaluation_git_sha)
            and hardware_class != "local-cpu"
            and evaluation_region != "local"
        ):
            raise ValueError(
                "held-out evaluation requires immutable image, Git, and cloud hardware identity"
            )
        evaluation = validate_config(config, EvaluationRunConfig)
        training = _latest_summary(evaluation.candidate_summary)
        training_result = training["result"]
        candidate_id = str(training_result["candidate_model_id"])
        checkpoint = Path(str(training_result["checkpoint"]))
        checkpoint_checksum = str(training_result["checkpoint_checksum"])
        config_hash = str(training_result["config_hash"])
        actual_checkpoint_checksum = f"sha256:{sha256_directory(checkpoint)}"
        if actual_checkpoint_checksum != checkpoint_checksum:
            raise ValueError("candidate checkpoint checksum no longer matches its training summary")
        frozen_config = Path(str(training_result.get("frozen_config", training["config_path"])))
        experiment = load_frozen_experiment(frozen_config)
        if experiment.config_hash != config_hash:
            raise ValueError("training summary config hash does not match the frozen configuration")
        text_column = (
            "text_title_v1"
            if experiment.input_template_version == "title_v1"
            else "text_enriched_v1"
        )
        baseline_run = _latest_summary(evaluation.baseline_summary)
        baseline_artifact_path = Path(str(baseline_run["result"]["baseline_summary"]))
        expected_baseline_hash = baseline_run["artifact_hashes"].get("baseline_summary")
        baseline_artifact_hash = f"sha256:{sha256_file(baseline_artifact_path)}"
        if expected_baseline_hash != baseline_artifact_hash:
            raise ValueError("baseline declaration differs from its completed run summary")
        baseline_artifact = _read_json(baseline_artifact_path)
        if baseline_artifact["split"] != "validation":
            raise ValueError("the strongest unchanged baseline must be selected on validation")
        selected_baseline_id = str(baseline_artifact["strongest_baseline_id"])
        if (
            evaluation.strongest_baseline_id is not None
            and evaluation.strongest_baseline_id != selected_baseline_id
        ):
            raise ValueError("evaluation baseline override differs from validation selection")
        baseline_id = selected_baseline_id
        pinned_model = Path("configs/models/cross-encoder-minilm-l6-v2.yaml")
        pretrained_root_id = _pretrained_id(pinned_model)
        pretrained_id = f"{pretrained_root_id}-enriched_v1"
        declared_baselines = tuple(
            sorted(
                (
                    bm25_model_id(text_column="text_title_v1"),
                    bm25_model_id(text_column="text_enriched_v1"),
                    f"{pretrained_root_id}-title_v1",
                    pretrained_id,
                )
            )
        )
        evaluated_manifest, _ = load_dataset_manifest(evaluation.dataset_manifest)
        evaluated_manifest_hash = evaluated_manifest.processed_checksum
        if evaluated_manifest_hash != training_result["dataset_manifest_hash"]:
            raise ValueError("evaluation dataset manifest differs from the trained candidate")
        if evaluated_manifest_hash != baseline_artifact["dataset_manifest_hash"]:
            raise ValueError("evaluation dataset manifest differs from the baseline declaration")
        receipt = _heldout_receipt(
            heldout=heldout,
            split=evaluation.split,
            config_hash=config_hash,
            evaluation_config_checksum=frozen_evaluation_checksum,
            checkpoint_checksum=checkpoint_checksum,
            baselines=declared_baselines,
        )
        frame, _ = load_prepared_split(
            evaluation.dataset_manifest,
            evaluation.split,
            heldout_receipt=receipt,
        )
        candidate_model = CrossEncoder(str(checkpoint), device="cpu", trust_remote_code=False)
        candidate_records = rank_cross_encoder(
            frame,
            model=candidate_model,
            model_id=candidate_id,
            text_column=text_column,
        )
        del candidate_model
        clean_hashes = (_ranking_hash(candidate_records, include_scores=True),)
        bm25_title = rank_bm25(frame, text_column="text_title_v1")
        bm25_enriched = rank_bm25(frame, text_column="text_enriched_v1")
        pretrained = load_unchanged_model(pinned_model, device="cpu")
        pretrained_title = rank_cross_encoder(
            frame,
            model=pretrained,
            model_id=f"{_pretrained_id(pinned_model)}-title_v1",
            text_column="text_title_v1",
        )
        pretrained_enriched = rank_cross_encoder(
            frame,
            model=pretrained,
            model_id=pretrained_id,
            text_column="text_enriched_v1",
        )
        baselines = {
            bm25_title[0].model_id: bm25_title,
            bm25_enriched[0].model_id: bm25_enriched,
            pretrained_title[0].model_id: pretrained_title,
            pretrained_enriched[0].model_id: pretrained_enriched,
        }
        if tuple(sorted(baselines)) != declared_baselines:
            raise ValueError("held-out receipt does not match the evaluated baseline set")
        if baseline_id and baseline_id not in baselines:
            raise ValueError(f"frozen strongest baseline is unavailable: {baseline_id}")
        clean_values = (_metric(candidate_records),)
        report = evaluate_systems(
            frame=frame,
            candidate_records=candidate_records,
            baseline_records=baselines,
            candidate_model_id=candidate_id,
            strongest_baseline_id=baseline_id,
            split=evaluation.split,
            report_id=f"report-{run.run_id}",
            run_id=run.run_id,
            bootstrap_resamples=evaluation.bootstrap_resamples,
            bootstrap_seed=evaluation.bootstrap_seed,
            confidence_level=evaluation.confidence_level,
            test_access_count=receipt.test_access_count if receipt else 0,
            training_runtime_seconds=float(training_result["duration_seconds"]),
            training_hardware=str(
                training_result.get("hardware_class", "training-hardware-not-recorded")
            ),
            evaluation_hardware=hardware_class,
            model_artifact_size_bytes=sum(
                item.stat().st_size for item in checkpoint.rglob("*") if item.is_file()
            ),
            actual_cost_usd=None,
            cost_evidence_source="not reconciled; command does not query billing records",
            evaluation_started_monotonic=evaluation_started,
            slice_min_query_count=evaluation.slice_min_query_count,
            reproduction_tolerance=evaluation.reproduction_tolerance,
            clean_run_metric_values=clean_values,
            clean_runs_match_artifacts=True,
            configuration_frozen=True,
            limitations=[
                "Candidate reranks only the supplied curated candidate set.",
                "Public labels are benchmark annotations, not live behavioral feedback.",
            ],
        )
        report_path = write_evaluation_report(report, run.run_dir / "evaluation-report.json")
        curated_path = write_curated_queries(
            run.run_dir / "curated-queries.json",
            _curated(
                frame,
                required_query_ids=tuple(item.query_id for item in report.example_results),
            ),
        )
        universe_hashes = {
            candidate_id: _candidate_universe_hash(candidate_records),
            **{
                model_id: _candidate_universe_hash(records)
                for model_id, records in baselines.items()
            },
        }
        single_provenance = EvaluationProvenance.model_validate(
            {
                "schema_version": "1.0.0",
                "artifact_type": "evaluation_provenance",
                "report_id": report.report_id,
                "split": evaluation.split,
                "config_hash": config_hash,
                "evaluation_config_checksum": frozen_evaluation_checksum,
                "staged_evaluation_config_checksum": staged_evaluation_checksum,
                "evaluation_image_digest": evaluation_image_digest or "unavailable",
                "evaluation_git_sha": evaluation_git_sha or "unavailable",
                "hardware_class": hardware_class,
                "region": evaluation_region,
                "training_strategy": experiment.sampling_strategy,
                "frozen_config": str(frozen_config.resolve()),
                "checkpoint_checksum": checkpoint_checksum,
                "dataset_manifest_hash": evaluated_manifest_hash,
                "split_manifest_hash": evaluated_manifest.split_manifest_hash,
                "dataset_name": evaluated_manifest.dataset_name,
                "dataset_version": evaluated_manifest.dataset_version,
                "dataset_locale": evaluated_manifest.locale,
                "strongest_baseline_id": report.primary_metric.strongest_baseline_id,
                "validation_baseline_summary_checksum": baseline_artifact_hash,
                "candidate_universe_hash": universe_hashes[candidate_id],
                "system_universe_hashes": universe_hashes,
                "candidate_lists_aligned": len(set(universe_hashes.values())) == 1,
                "clean_run_metric_values": clean_values,
                "clean_ranking_hashes": clean_hashes,
                "independent_evaluation_count": 1,
                "slice_min_query_count": evaluation.slice_min_query_count,
                "reproduction_tolerance": evaluation.reproduction_tolerance,
                "evaluated_baseline_model_ids": list(declared_baselines),
                "test_access_count": receipt.test_access_count if receipt else 0,
                "source_evaluations": [],
            }
        )
        provenance_path = run.run_dir / "evaluation-provenance.json"
        provenance_path.write_text(
            single_provenance.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        run.add_artifact("evaluation_report", report_path)
        run.add_artifact("curated_queries", curated_path)
        run.add_artifact("evaluation_provenance", provenance_path)
        _success(
            run,
            {
                "report_id": report.report_id,
                "evaluation_report": str(report_path.resolve()),
                "curated_queries": str(curated_path.resolve()),
                "candidate_model_id": candidate_id,
                "promoted_model_id": report.release_gate_results.promoted_model_id,
                "release_gate_passed": report.release_gate_results.passed,
                "primary_metric": report.primary_metric.model_dump(mode="json"),
                "config_hash": config_hash,
                "checkpoint": str(checkpoint.resolve()),
                "checkpoint_checksum": checkpoint_checksum,
                "dataset_manifest_hash": evaluated_manifest_hash,
                "split_manifest_hash": evaluated_manifest.split_manifest_hash,
                "evaluation_provenance": str(provenance_path.resolve()),
                "evaluation_config_checksum": frozen_evaluation_checksum,
                "evaluation_image_digest": evaluation_image_digest,
                "evaluation_git_sha": evaluation_git_sha or "unavailable",
                "hardware_class": hardware_class,
                "region": evaluation_region,
                "training_strategy": experiment.sampling_strategy,
                "input_template_version": experiment.input_template_version,
                "base_model_id": experiment.base_model_id,
                "base_model_revision": experiment.base_model_revision,
            },
        )
    except (OSError, KeyError, ValueError, ValidationError, RuntimeError, AssertionError) as error:
        _abort(run, error)


def _evaluation_source(
    reference: Path,
) -> tuple[dict[str, Any], EvaluationReport, dict[str, Any], Path, Path]:
    summary = _latest_summary(reference)
    command = CommandSummary.model_validate(summary)
    if command.command != "evaluate" or command.status != "succeeded":
        raise ValueError("clean-run source must be a successful evaluate command summary")
    result = command.result
    hashes = command.artifact_hashes
    if not isinstance(result, dict) or not isinstance(hashes, dict):
        raise ValueError("evaluation source is missing result or artifact hashes")
    expected_artifacts = {"evaluation_report", "evaluation_provenance", "curated_queries"}
    if set(hashes) != expected_artifacts:
        raise ValueError("clean-run command artifact inventory is not exact")
    summary_dir = reference.resolve().parent
    report_path = Path(str(result.get("evaluation_report", "")))
    provenance_path = Path(str(result.get("evaluation_provenance", "")))
    curated_path = Path(str(result.get("curated_queries", "")))
    if not report_path.is_file():
        report_path = summary_dir / "evaluation-report.json"
    if not provenance_path.is_file():
        provenance_path = summary_dir / "evaluation-provenance.json"
    if not curated_path.is_file():
        curated_path = summary_dir / "curated-queries.json"
    expected_report = str(hashes.get("evaluation_report", ""))
    expected_provenance = str(hashes.get("evaluation_provenance", ""))
    expected_curated = str(hashes.get("curated_queries", ""))
    if expected_report != f"sha256:{sha256_file(report_path)}":
        raise ValueError("clean-run evaluation report checksum mismatch")
    if expected_provenance != f"sha256:{sha256_file(provenance_path)}":
        raise ValueError("clean-run evaluation provenance checksum mismatch")
    if expected_curated != f"sha256:{sha256_file(curated_path)}":
        raise ValueError("clean-run curated-query checksum mismatch")
    report = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    provenance = EvaluationProvenance.model_validate_json(
        provenance_path.read_text(encoding="utf-8")
    ).model_dump(mode="json")
    if provenance.get("report_id") != report.report_id:
        raise ValueError("clean-run report and provenance IDs differ")
    if command.run_id != report.run_id:
        raise ValueError("clean-run command and report run IDs differ")
    if command.repository_dirty:
        raise ValueError("clean-run command was produced from a dirty repository")
    if command.git_sha != provenance.get("evaluation_git_sha"):
        raise ValueError("clean-run command and provenance Git revisions differ")
    return summary, report, provenance, report_path, provenance_path


@app.command("bind-clean-evaluations")
def bind_clean_evaluations(
    first_summary: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    second_summary: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Bind two independent held-out evaluations without reopening the test data."""

    configure_logging()
    run = CommandRun("bind-clean-evaluations", None)
    try:
        sources = [
            _evaluation_source(first_summary),
            _evaluation_source(second_summary),
        ]
        sources.sort(key=lambda item: item[1].test_access_count)
        first, second = sources
        (
            first_summary_payload,
            first_report,
            first_provenance,
            first_report_path,
            first_prov_path,
        ) = first
        (
            second_summary_payload,
            second_report,
            second_provenance,
            second_report_path,
            second_prov_path,
        ) = second
        if first_report.split != "test" or second_report.split != "test":
            raise ValueError("clean-run binding accepts held-out test evaluations only")
        if second_report.test_access_count != first_report.test_access_count + 1:
            raise ValueError("clean-run test-access counters must be consecutive")
        if first_report.run_id == second_report.run_id:
            raise ValueError("clean evaluations must have distinct run IDs")

        first_result = first_summary_payload.get("result")
        second_result = second_summary_payload.get("result")
        if not isinstance(first_result, dict) or not isinstance(second_result, dict):
            raise ValueError("clean evaluation summaries have invalid result objects")

        identity_keys = (
            "config_hash",
            "evaluation_config_checksum",
            "staged_evaluation_config_checksum",
            "checkpoint_checksum",
            "dataset_manifest_hash",
            "split_manifest_hash",
            "dataset_name",
            "dataset_version",
            "dataset_locale",
            "strongest_baseline_id",
            "validation_baseline_summary_checksum",
            "candidate_universe_hash",
            "system_universe_hashes",
            "slice_min_query_count",
            "reproduction_tolerance",
            "evaluated_baseline_model_ids",
            "evaluation_image_digest",
            "evaluation_git_sha",
            "hardware_class",
            "region",
            "training_strategy",
        )
        for key in identity_keys:
            if first_provenance.get(key) != second_provenance.get(key):
                raise ValueError(f"clean evaluations differ in immutable identity: {key}")
        if not SHA256_PATTERN.fullmatch(str(first_provenance["evaluation_config_checksum"])):
            raise ValueError("clean evaluations lack a canonical evaluation-config checksum")
        if not SHA256_PATTERN.fullmatch(str(first_provenance["evaluation_image_digest"])):
            raise ValueError("clean evaluations lack an immutable image digest")
        if re.fullmatch(r"[0-9a-f]{40}", str(first_provenance["evaluation_git_sha"])) is None:
            raise ValueError("clean evaluations lack a full immutable Git revision")

        summary_identity_keys = (
            "candidate_model_id",
            "checkpoint_checksum",
            "config_hash",
            "dataset_manifest_hash",
            "split_manifest_hash",
            "evaluation_config_checksum",
            "evaluation_image_digest",
            "evaluation_git_sha",
            "hardware_class",
            "region",
            "training_strategy",
            "input_template_version",
            "base_model_id",
            "base_model_revision",
            "primary_metric",
        )
        for key in summary_identity_keys:
            if key not in first_result or key not in second_result:
                raise ValueError(f"clean evaluation summaries lack frozen identity: {key}")
            if first_result[key] != second_result[key]:
                raise ValueError(f"clean evaluation summaries differ in frozen identity: {key}")

        for label, result, report, provenance in (
            ("first", first_result, first_report, first_provenance),
            ("second", second_result, second_report, second_provenance),
        ):
            expected_summary_identity = {
                "candidate_model_id": report.candidate_model_id,
                "checkpoint_checksum": provenance["checkpoint_checksum"],
                "config_hash": provenance["config_hash"],
                "dataset_manifest_hash": provenance["dataset_manifest_hash"],
                "split_manifest_hash": provenance["split_manifest_hash"],
                "evaluation_config_checksum": provenance["evaluation_config_checksum"],
                "evaluation_image_digest": provenance["evaluation_image_digest"],
                "evaluation_git_sha": provenance["evaluation_git_sha"],
                "hardware_class": provenance["hardware_class"],
                "region": provenance["region"],
                "training_strategy": provenance["training_strategy"],
                "primary_metric": report.primary_metric.model_dump(mode="json"),
            }
            for key, expected in expected_summary_identity.items():
                if result.get(key) != expected:
                    raise ValueError(
                        f"{label} clean evaluation summary is not bound to its evidence: {key}"
                    )
            if report.evaluation_runtime.hardware != provenance["hardware_class"]:
                raise ValueError(
                    f"{label} clean evaluation report is not bound to its hardware identity"
                )

        report_identity = (
            "candidate_model_id",
            "baseline_model_ids",
            "query_count",
            "excluded_query_count",
            "metric_definition_version",
            "bootstrap_method",
            "bootstrap_seed",
            "bootstrap_resamples",
            "confidence_level",
            "training_runtime",
        )
        for field in report_identity:
            if getattr(first_report, field) != getattr(second_report, field):
                raise ValueError(f"clean evaluation reports differ in {field}")
        if first_report.primary_metric != second_report.primary_metric:
            raise ValueError("clean evaluation reports differ in primary metric evidence")
        if first_report.paired_differences != second_report.paired_differences:
            raise ValueError("clean evaluation reports differ in paired-difference evidence")
        if first_report.slice_results != second_report.slice_results:
            raise ValueError("clean evaluation reports differ in release-gated slice evidence")

        slice_min_query_count = int(first_provenance["slice_min_query_count"])
        for label, report in (("first", first_report), ("second", second_report)):
            for item in report.slice_results:
                derived_adequacy = item.query_count >= slice_min_query_count
                if item.adequate_sample_size != derived_adequacy:
                    raise ValueError(
                        f"{label} clean evaluation slice adequacy is inconsistent with "
                        f"the frozen minimum query count: {item.dimension}/{item.slice_name}"
                    )

        clean_ranking_hashes = [
            str(first_provenance["clean_ranking_hashes"][0]),
            str(second_provenance["clean_ranking_hashes"][0]),
        ]
        if clean_ranking_hashes[0] != clean_ranking_hashes[1]:
            raise ValueError("clean evaluations produced different candidate ranking hashes")

        clean_values = (
            float(first_report.primary_metric.candidate_value),
            float(second_report.primary_metric.candidate_value),
        )
        for report, provenance in (
            (first_report, first_provenance),
            (second_report, second_provenance),
        ):
            recorded = tuple(float(value) for value in provenance["clean_run_metric_values"])
            if recorded != (float(report.primary_metric.candidate_value),):
                raise ValueError("clean-run metric does not match its evaluation report")
            if int(provenance.get("independent_evaluation_count", 0)) != 1:
                raise ValueError("each source must represent exactly one clean evaluation")

        def primary_interval(report: EvaluationReport) -> PairedDifference:
            intervals = [
                interval
                for interval in report.paired_differences
                if interval.baseline_model_id == report.primary_metric.strongest_baseline_id
                and interval.metric_name == report.primary_metric.metric_name
            ]
            if len(intervals) != 1:
                raise ValueError(
                    "each clean report must contain exactly one primary strongest-baseline interval"
                )
            interval = intervals[0]
            interval_identity = {
                "candidate model": interval.candidate_model_id == report.candidate_model_id,
                "point estimate": math.isclose(
                    interval.point_estimate,
                    report.primary_metric.candidate_minus_baseline,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ),
                "confidence level": interval.confidence_level == report.confidence_level,
                "query count": interval.query_count == report.query_count,
                "excluded query count": (
                    interval.excluded_query_count == report.excluded_query_count
                ),
                "bootstrap seed": interval.bootstrap_seed == report.bootstrap_seed,
                "bootstrap resamples": (interval.bootstrap_resamples == report.bootstrap_resamples),
            }
            failures = [name for name, matches in interval_identity.items() if not matches]
            if failures:
                raise ValueError(
                    "primary paired interval is not bound to its report: " + ", ".join(failures)
                )
            return interval

        first_interval = primary_interval(first_report)
        second_interval = primary_interval(second_report)
        configuration_frozen = all(
            first_provenance[key] == second_provenance[key] for key in identity_keys
        )
        reports_match_release_evidence = (
            all(
                getattr(first_report, field) == getattr(second_report, field)
                for field in report_identity
            )
            and first_report.primary_metric == second_report.primary_metric
            and first_report.paired_differences == second_report.paired_differences
            and first_report.slice_results == second_report.slice_results
        )
        clean_runs_match_artifacts = (
            configuration_frozen
            and reports_match_release_evidence
            and clean_ranking_hashes[0] == clean_ranking_hashes[1]
            and all(first_result[key] == second_result[key] for key in summary_identity_keys)
        )
        candidate_lists_aligned = bool(
            first_provenance["candidate_lists_aligned"]
            and second_provenance["candidate_lists_aligned"]
        )

        def recompute_gate(
            report: EvaluationReport, interval: PairedDifference
        ) -> ReleaseGateResult:
            slice_regressions = tuple(
                float(item.point_estimate)
                for item in report.slice_results
                if item.query_count >= slice_min_query_count
                and item.point_estimate is not None
                and item.point_estimate < 0
            )
            return evaluate_release_gate(
                ReleaseGateInputs(
                    candidate_model_id=report.candidate_model_id,
                    strongest_baseline_model_id=report.primary_metric.strongest_baseline_id,
                    candidate_ndcg_at_10=report.primary_metric.candidate_value,
                    baseline_ndcg_at_10=report.primary_metric.strongest_baseline_value,
                    difference_ci_lower=interval.ci_lower,
                    difference_ci_upper=interval.ci_upper,
                    confidence_level=report.confidence_level,
                    relevance_mapping_version=report.metric_definition_version,
                    resampling_unit=interval.resampling_unit,
                    bootstrap_seed=report.bootstrap_seed,
                    bootstrap_resamples=report.bootstrap_resamples,
                    query_count=report.query_count,
                    excluded_query_count=report.excluded_query_count,
                    test_access_count=second_report.test_access_count,
                    clean_run_metric_values=clean_values,
                    candidate_lists_aligned=candidate_lists_aligned,
                    configuration_frozen=configuration_frozen,
                    clean_runs_match_artifacts=clean_runs_match_artifacts,
                    unexplained_slice_deltas=slice_regressions,
                ),
                ReleaseGateConfig(
                    reproducibility_tolerance=float(first_provenance["reproduction_tolerance"])
                ),
            )

        first_gate = recompute_gate(first_report, first_interval)
        second_gate = recompute_gate(second_report, second_interval)
        if first_gate != second_gate:
            raise ValueError("clean evaluation reports produce different final release gates")
        gate = first_gate
        bound_report = EvaluationReport.model_validate(
            first_report.model_copy(
                update={
                    "report_id": f"report-{run.run_id}",
                    "run_id": run.run_id,
                    "test_access_count": second_report.test_access_count,
                    "release_gate_results": gate,
                    "limitations": [
                        *first_report.limitations,
                        "The first clean evaluation is the selected report; the second is an independent reproducibility check.",
                    ],
                    "created_at": datetime.now(UTC),
                }
            ).model_dump(mode="json")
        )
        report_path = write_evaluation_report(bound_report, run.run_dir / "evaluation-report.json")
        bound_provenance = EvaluationProvenance.model_validate(
            {
                **{key: first_provenance[key] for key in identity_keys},
                "schema_version": "1.0.0",
                "artifact_type": "evaluation_provenance",
                "report_id": bound_report.report_id,
                "split": "test",
                "frozen_config": first_provenance["frozen_config"],
                "candidate_lists_aligned": bool(
                    first_provenance["candidate_lists_aligned"]
                    and second_provenance["candidate_lists_aligned"]
                ),
                "clean_run_metric_values": list(clean_values),
                "clean_ranking_hashes": clean_ranking_hashes,
                "independent_evaluation_count": 2,
                "test_access_count": second_report.test_access_count,
                "source_evaluations": [
                    {
                        "run_id": report.run_id,
                        "report_id": report.report_id,
                        "report_checksum": f"sha256:{sha256_file(report_path_source)}",
                        "provenance_checksum": f"sha256:{sha256_file(provenance_path_source)}",
                        "test_access_count": report.test_access_count,
                        "candidate_metric": report.primary_metric.candidate_value,
                        "candidate_ranking_hash": ranking_hash,
                    }
                    for report, report_path_source, provenance_path_source, ranking_hash in (
                        (
                            first_report,
                            first_report_path,
                            first_prov_path,
                            clean_ranking_hashes[0],
                        ),
                        (
                            second_report,
                            second_report_path,
                            second_prov_path,
                            clean_ranking_hashes[1],
                        ),
                    )
                ],
            }
        )
        provenance_path = run.run_dir / "evaluation-provenance.json"
        provenance_path.write_text(
            bound_provenance.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        curated_candidates = [
            Path(str(first_result["curated_queries"])),
            Path(str(second_result["curated_queries"])),
        ]
        for index, path in enumerate(curated_candidates):
            if not path.is_file():
                path = (
                    first_summary if index == 0 else second_summary
                ).resolve().parent / "curated-queries.json"
                curated_candidates[index] = path
        if sha256_file(curated_candidates[0]) != sha256_file(curated_candidates[1]):
            raise ValueError("clean evaluations produced different curated-query evidence")
        curated_path = run.run_dir / "curated-queries.json"
        curated_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(curated_candidates[0], curated_path)
        run.add_artifact("evaluation_report", report_path)
        run.add_artifact("evaluation_provenance", provenance_path)
        run.add_artifact("curated_queries", curated_path)
        _success(
            run,
            {
                **{
                    key: first_result[key]
                    for key in (
                        "candidate_model_id",
                        "checkpoint",
                        "checkpoint_checksum",
                        "config_hash",
                        "dataset_manifest_hash",
                        "split_manifest_hash",
                        "input_template_version",
                        "base_model_id",
                        "base_model_revision",
                        "region",
                        "training_strategy",
                    )
                },
                "report_id": bound_report.report_id,
                "evaluation_report": str(report_path.resolve()),
                "evaluation_provenance": str(provenance_path.resolve()),
                "curated_queries": str(curated_path.resolve()),
                "release_gate_passed": gate.passed,
                "promoted_model_id": gate.promoted_model_id,
                "clean_evaluation_count": 2,
            },
        )
    except (
        OSError,
        StopIteration,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        _abort(run, error)


def _find_report(report_id: str) -> Path:
    direct = Path(report_id)
    if direct.is_file():
        return direct
    for candidate in Path("artifacts/runs").glob("*/evaluation-report.json"):
        payload = _read_json(candidate)
        if payload.get("report_id") == report_id:
            return candidate
    raise FileNotFoundError(f"evaluation report not found: {report_id}")


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    value = result.stdout.strip()
    if result.returncode or len(value) < 7:
        raise ValueError("promotion requires a committed Git revision")
    return value


@app.command("promote")
def promote(
    report_id: Annotated[str, typer.Option("--report-id")],
    trial_selection: Annotated[
        Path, typer.Option("--trial-selection", exists=True, dir_okay=False, readable=True)
    ],
    selected_training_run_manifest: Annotated[
        Path,
        typer.Option(
            "--selected-training-run-manifest",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    selected_training_model_artifact: Annotated[
        Path,
        typer.Option(
            "--selected-training-model-artifact",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    evaluation_runtime_seconds: Annotated[
        float, typer.Option("--evaluation-runtime-seconds", min=0)
    ],
    evaluation_estimated_cost_usd: Annotated[
        float, typer.Option("--evaluation-estimated-cost-usd", min=0)
    ],
    evaluation_actual_cost_usd: Annotated[
        float | None, typer.Option("--evaluation-actual-cost-usd", min=0)
    ] = None,
) -> None:
    """Create an immutable, fail-closed release bundle from an evaluation report."""

    configure_logging()
    run = CommandRun("promote", None)
    try:
        report_path = _find_report(report_id)
        report = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        evaluation_summary = _latest_summary(report_path.parent / "summary.json")
        expected_report_hash = evaluation_summary["artifact_hashes"].get("evaluation_report")
        if expected_report_hash != f"sha256:{sha256_file(report_path)}":
            raise ValueError("evaluation report differs from its completed run summary")
        if report.split.casefold() != "test":
            raise ValueError("only a guarded held-out evaluation can create a release")
        result = evaluation_summary["result"]
        checkpoint = Path(str(result["checkpoint"]))
        if f"sha256:{sha256_directory(checkpoint)}" != result["checkpoint_checksum"]:
            raise ValueError("candidate checkpoint differs from the evaluated artifact")
        provenance_path = Path(str(result["evaluation_provenance"]))
        expected_provenance_hash = evaluation_summary["artifact_hashes"].get(
            "evaluation_provenance"
        )
        if expected_provenance_hash != f"sha256:{sha256_file(provenance_path)}":
            raise ValueError("evaluation provenance differs from its completed run summary")
        provenance_contract = EvaluationProvenance.model_validate_json(
            provenance_path.read_text(encoding="utf-8")
        )
        provenance = provenance_contract.model_dump(mode="json")
        if not SHA256_PATTERN.fullmatch(str(provenance["split_manifest_hash"])):
            raise ValueError("evaluation provenance lacks a canonical split manifest hash")
        if provenance["report_id"] != report.report_id:
            raise ValueError("evaluation report and provenance IDs differ")
        if (
            provenance["split"] != "test"
            or provenance["test_access_count"] != report.test_access_count
        ):
            raise ValueError("held-out provenance does not match the evaluation report")
        if (
            provenance["checkpoint_checksum"] != result["checkpoint_checksum"]
            or provenance["config_hash"] != result["config_hash"]
            or provenance["dataset_manifest_hash"] != result["dataset_manifest_hash"]
            or provenance["split_manifest_hash"] != result["split_manifest_hash"]
            or provenance["strongest_baseline_id"] != report.primary_metric.strongest_baseline_id
        ):
            raise ValueError("evaluation provenance does not match the evaluated inputs")
        frozen = load_frozen_experiment(str(provenance["frozen_config"]))
        if frozen.config_hash != provenance["config_hash"]:
            raise ValueError("frozen configuration no longer matches held-out provenance")
        selection = TrialSelection.model_validate_json(trial_selection.read_text(encoding="utf-8"))
        selection_checksum = f"sha256:{sha256_file(trial_selection)}"
        treatment = next(
            (trial for trial in selection.trials if trial.role == "candidate_treatment"),
            None,
        )
        if treatment is None:
            raise ValueError("trial selection has no candidate treatment")
        training_manifest_checksum = f"sha256:{sha256_file(selected_training_run_manifest)}"
        if training_manifest_checksum != treatment.training_run_manifest_sha256:
            raise ValueError("selected training RunManifest checksum differs from the selection")
        training_manifest = RunManifest.model_validate_json(
            selected_training_run_manifest.read_text(encoding="utf-8")
        )
        expected_training_manifest = {
            "run_id": treatment.candidate_run_id,
            "run_type": "training",
            "git_sha": selection.git_sha,
            "repository_dirty": False,
            "image_digest": treatment.training_image_digest,
            "config_hash": treatment.candidate_training_config_sha256,
            "dataset_manifest_hash": selection.dataset_manifest_hash,
            "region": treatment.region,
            "job_id": treatment.training_job_id,
            "hardware": treatment.hardware_class,
            "accelerator": treatment.accelerator,
            "status": "succeeded",
        }
        for field, expected in expected_training_manifest.items():
            if getattr(training_manifest, field) != expected:
                raise ValueError(f"selected training RunManifest disagrees on {field}")
        if training_manifest.duration_seconds is None:
            raise ValueError("selected training RunManifest has no measured duration")
        source_model_artifact_checksum = f"sha256:{sha256_file(selected_training_model_artifact)}"
        source_model_artifact = ModelArtifact.model_validate_json(
            selected_training_model_artifact.read_text(encoding="utf-8")
        )
        expected_source_artifact = {
            "model_id": treatment.candidate_model_id,
            "run_id": training_manifest.run_id,
            "base_model_id": frozen.base_model_id,
            "base_model_revision": frozen.base_model_revision,
            "tokenizer_revision": frozen.base_model_revision,
            "checkpoint_uri": "candidate/best",
            "artifact_checksum": treatment.candidate_checkpoint_sha256,
            "config_id": treatment.config_id,
            "config_hash": training_manifest.config_hash,
            "dataset_manifest_hash": training_manifest.dataset_manifest_hash,
            "input_contract_version": treatment.input_template_version,
            "label_mapping_version": frozen.label_mapping_version,
            "sampling_strategy": treatment.sampling_strategy,
            "hard_example_sources": treatment.hard_example_sources,
            "promoted": False,
            "promotion_reason": "pending held-out evaluation",
            "evaluation_report_id": "not_evaluated",
            "git_sha": training_manifest.git_sha,
            "image_digest": training_manifest.image_digest,
        }
        for field, expected in expected_source_artifact.items():
            if getattr(source_model_artifact, field) != expected:
                raise ValueError(f"selected training ModelArtifact disagrees on {field}")
        if any(
            value is not None
            for value in (
                source_model_artifact.source_model_artifact_sha256,
                source_model_artifact.selected_training_run_manifest_sha256,
                source_model_artifact.evaluation_report_sha256,
            )
        ):
            raise ValueError("selected training ModelArtifact already claims release bindings")
        actual_training = source_model_artifact.training_result
        if (
            actual_training.device_type != training_manifest.device_type
            or actual_training.cuda_available != training_manifest.cuda_available
            or actual_training.cuda_device_count != training_manifest.cuda_device_count
            or actual_training.accelerator_type != training_manifest.accelerator
        ):
            raise ValueError("selected ModelArtifact and RunManifest execution evidence differ")
        if (
            selection.selected_candidate_run_id != training_manifest.run_id
            or selection.selected_candidate_model_id != report.candidate_model_id
            or selection.selected_candidate_config_sha256 != provenance["config_hash"]
            or selection.dataset_manifest_hash != provenance["dataset_manifest_hash"]
            or selection.git_sha != provenance["evaluation_git_sha"]
            or treatment.candidate_checkpoint_sha256 != provenance["checkpoint_checksum"]
        ):
            raise ValueError(
                "trial selection, selected training run, and held-out evaluation are not identical"
            )
        if int(provenance["independent_evaluation_count"]) != 2:
            raise ValueError("public release requires exactly two clean evaluation executions")
        training_provenance = PublicTrainingProvenance(
            trial_selection_id=selection.selection_id,
            trial_selection_sha256=selection_checksum,
            run_id=training_manifest.run_id,
            run_manifest_sha256=training_manifest_checksum,
            selected_model_id=selection.selected_candidate_model_id,
            selected_model_artifact_checksum=treatment.candidate_checkpoint_sha256,
            config_hash=training_manifest.config_hash,
            git_sha=training_manifest.git_sha,
            image_digest=training_manifest.image_digest,
            hardware_class=treatment.hardware_class,
            accelerator=treatment.accelerator,
            region=treatment.region,
            runtime_seconds=training_manifest.duration_seconds,
            estimated_cost_usd=training_manifest.estimated_cost_usd,
            actual_cost_usd=training_manifest.actual_cost_usd,
            cost_evidence=(
                "Selected training RunManifest estimate; final managed-service charge is not "
                "yet reconciled."
                if training_manifest.actual_cost_usd is None
                else "Selected training RunManifest with reconciled actual cost."
            ),
        )
        evaluation_hardware = provenance_contract.hardware_class
        evaluation_region = provenance_contract.region
        if evaluation_hardware != "ml.m5.xlarge" or evaluation_region != "us-east-1":
            raise ValueError("public held-out provenance requires the fixed cloud environment")
        evaluation_provenance = PublicEvaluationProvenance(
            candidate_model_id=report.candidate_model_id,
            candidate_model_artifact_checksum=treatment.candidate_checkpoint_sha256,
            evaluation_config_hash=str(provenance["evaluation_config_checksum"]),
            git_sha=str(provenance["evaluation_git_sha"]),
            image_digest=str(provenance["evaluation_image_digest"]),
            hardware_class=evaluation_hardware,
            region=evaluation_region,
            clean_execution_count=2,
            runtime_seconds=evaluation_runtime_seconds,
            runtime_basis="processing_job_wall_clock_sum",
            estimated_cost_usd=evaluation_estimated_cost_usd,
            actual_cost_usd=evaluation_actual_cost_usd,
            cost_evidence=(
                "Live on-demand upper bound for two clean Processing jobs; final charge is not "
                "yet reconciled."
                if evaluation_actual_cost_usd is None
                else "Two clean Processing jobs with reconciled actual cost."
            ),
        )
        primary_interval = next(
            interval
            for interval in report.paired_differences
            if interval.baseline_model_id == report.primary_metric.strongest_baseline_id
            and interval.metric_name == "graded_ndcg@10"
        )
        clean_values = tuple(float(value) for value in provenance["clean_run_metric_values"])
        slice_regressions = tuple(
            float(item.point_estimate)
            for item in report.slice_results
            if item.adequate_sample_size
            and item.point_estimate is not None
            and item.point_estimate < 0
        )
        recomputed_gate = evaluate_release_gate(
            ReleaseGateInputs(
                candidate_model_id=report.candidate_model_id,
                strongest_baseline_model_id=report.primary_metric.strongest_baseline_id,
                candidate_ndcg_at_10=report.primary_metric.candidate_value,
                baseline_ndcg_at_10=report.primary_metric.strongest_baseline_value,
                difference_ci_lower=primary_interval.ci_lower,
                difference_ci_upper=primary_interval.ci_upper,
                confidence_level=report.confidence_level,
                relevance_mapping_version=report.metric_definition_version,
                resampling_unit=primary_interval.resampling_unit,
                bootstrap_seed=report.bootstrap_seed,
                bootstrap_resamples=report.bootstrap_resamples,
                query_count=report.query_count,
                excluded_query_count=report.excluded_query_count,
                test_access_count=report.test_access_count,
                clean_run_metric_values=clean_values,
                candidate_lists_aligned=bool(provenance["candidate_lists_aligned"]),
                configuration_frozen=True,
                clean_runs_match_artifacts=(
                    int(provenance["independent_evaluation_count"]) >= 2
                    and len(provenance["source_evaluations"]) >= 2
                    and all(
                        SHA256_PATTERN.fullmatch(str(source["report_checksum"]))
                        and SHA256_PATTERN.fullmatch(str(source["provenance_checksum"]))
                        for source in provenance["source_evaluations"]
                    )
                    and provenance["checkpoint_checksum"] == result["checkpoint_checksum"]
                    and provenance["config_hash"] == result["config_hash"]
                ),
                unexplained_slice_deltas=slice_regressions,
            ),
            ReleaseGateConfig(
                reproducibility_tolerance=float(provenance["reproduction_tolerance"]),
            ),
        )
        if recomputed_gate != report.release_gate_results:
            raise ValueError("stored release decision does not match the recomputed gate")
        release_root = Path("artifacts/releases")
        release_root.mkdir(parents=True, exist_ok=True)
        final_release_dir = release_root / report.report_id
        if final_release_dir.exists():
            raise FileExistsError(f"immutable release already exists: {final_release_dir}")
        release_dir = Path(
            tempfile.mkdtemp(prefix=f".{report.report_id}-staging-", dir=release_root)
        )
        candidate_dir = release_dir / "models" / "candidate"
        shutil.copytree(checkpoint, candidate_dir)
        candidate_checksum = f"sha256:{sha256_directory(candidate_dir)}"
        candidate_size_bytes = sum(
            path.stat().st_size for path in candidate_dir.rglob("*") if path.is_file()
        )
        if (
            candidate_checksum != source_model_artifact.artifact_checksum
            or candidate_size_bytes != source_model_artifact.artifact_size_bytes
        ):
            raise ValueError("release checkpoint differs from the selected training ModelArtifact")
        pinned = Path("configs/models/cross-encoder-minilm-l6-v2.yaml")
        pinned_config = _read_yaml(pinned)
        curated_source = Path(str(result["curated_queries"]))
        shutil.copy2(curated_source, release_dir / "curated-queries.json")
        shutil.copy2(report_path, release_dir / "evaluation-report.json")
        shutil.copy2(provenance_path, release_dir / "evaluation-provenance.json")
        _copy_public_distribution_notices(release_dir)
        promoted_id = report.release_gate_results.promoted_model_id
        strongest_id = report.release_gate_results.baseline_model_id
        baseline_template = (
            "title_v1"
            if strongest_id.endswith("-title_v1") or "-text_title_v1-" in strongest_id
            else "enriched_v1"
        )
        if strongest_id.startswith("bm25-"):
            baseline_checksum = f"sha256:{sha256_value({'model_id': strongest_id})}"
            baseline_model: dict[str, Any] = {
                "model_id": strongest_id,
                "kind": "bm25",
                "text_template": baseline_template,
                "artifact_checksum": baseline_checksum,
                "public_summary": {
                    "model_id": strongest_id,
                    "display_name": "BM25 lexical baseline",
                    "kind": "bm25",
                    "base_model_id": None,
                    "artifact_checksum": baseline_checksum,
                    "evaluation_report_id": report.report_id,
                    "promoted_at": report.created_at if promoted_id == strongest_id else None,
                    "limitations_url": "/methodology#limitations",
                },
            }
        elif strongest_id.startswith("pretrained-cross-encoder@"):
            baseline_dir = release_dir / "models" / "pretrained"
            base_model = load_unchanged_model(pinned, device="cpu")
            base_model.save_pretrained(
                str(baseline_dir), create_model_card=False, safe_serialization=True
            )
            baseline_checksum = f"sha256:{sha256_directory(baseline_dir)}"
            baseline_model = {
                "model_id": strongest_id,
                "kind": "pretrained",
                "checkpoint": "models/pretrained",
                "text_template": baseline_template,
                "artifact_checksum": baseline_checksum,
                "batch_size": 32,
                "public_summary": {
                    "model_id": strongest_id,
                    "display_name": "Unchanged pretrained cross-encoder",
                    "kind": "pretrained",
                    "base_model_id": str(pinned_config["model_id"]),
                    "artifact_checksum": baseline_checksum,
                    "evaluation_report_id": report.report_id,
                    "promoted_at": report.created_at if promoted_id == strongest_id else None,
                    "limitations_url": "/methodology#limitations",
                },
            }
        else:
            raise ValueError(f"unsupported strongest baseline: {strongest_id}")
        candidate_template = frozen.input_template_version
        models: list[dict[str, Any]] = [
            baseline_model,
            {
                "model_id": report.candidate_model_id,
                "kind": "fine_tuned",
                "checkpoint": "models/candidate",
                "text_template": candidate_template,
                "artifact_checksum": candidate_checksum,
                "batch_size": 32,
                "public_summary": {
                    "model_id": report.candidate_model_id,
                    "display_name": "Fine-tuned candidate",
                    "kind": "fine_tuned",
                    "base_model_id": frozen.base_model_id,
                    "artifact_checksum": candidate_checksum,
                    "evaluation_report_id": report.report_id,
                    "promoted_at": report.created_at
                    if promoted_id == report.candidate_model_id
                    else None,
                    "limitations_url": "/methodology#limitations",
                },
            },
        ]
        if promoted_id not in {str(model["model_id"]) for model in models}:
            raise ValueError("promotion report references a model absent from the release bundle")
        promoted_model = next(model for model in models if str(model["model_id"]) == promoted_id)
        promoted_checksum = str(promoted_model["artifact_checksum"])
        if not SHA256_PATTERN.fullmatch(promoted_checksum):
            raise ValueError("promoted model checksum is not canonical SHA-256")
        public_run = PublicRunSummary(
            run_id=report.run_id,
            config_hash=str(provenance["config_hash"]),
            dataset_manifest_hash=str(provenance["dataset_manifest_hash"]),
            split_manifest_hash=str(provenance["split_manifest_hash"]),
            git_sha=str(provenance["evaluation_git_sha"]),
            model_artifact_checksum=promoted_checksum,
            dataset_name=str(provenance["dataset_name"]),
            dataset_version=str(provenance["dataset_version"]),
            locale=cast(Literal["us"], str(provenance["dataset_locale"])),
            base_model_id=frozen.base_model_id,
            base_model_revision=frozen.base_model_revision,
            training_strategy=str(provenance["training_strategy"]),
            training_provenance=training_provenance,
            evaluation_provenance=evaluation_provenance,
            metrics=public_run_metrics(report),
            intervals=public_run_intervals(report),
            test_access_count=report.test_access_count,
            limitations=report.limitations,
            prohibited_claims=[
                "No claim of full-catalog retrieval or marketplace search is allowed.",
                "No claim of online shopper, conversion, revenue, or production-scale impact is allowed.",
                "No claim of Amazon affiliation or official competition equivalence is allowed.",
            ],
            reproduction_command=(
                f"gh workflow run release.yml --ref {provenance['evaluation_git_sha']}"
            ),
        )
        public_evidence = build_public_evidence(
            report,
            public_run,
            QueryStore.from_json(release_dir / "curated-queries.json"),
            minimum_slice_size=int(provenance["slice_min_query_count"]),
        )
        public_evidence_path = write_public_evidence(
            public_evidence,
            release_dir / "public-evidence.json",
        )
        report_checksum = f"sha256:{sha256_file(release_dir / 'evaluation-report.json')}"
        candidate_promoted = report.release_gate_results.passed
        if candidate_promoted != (promoted_id == report.candidate_model_id):
            raise ValueError("held-out decision and active-model identity differ")
        final_model_artifact = ModelArtifact.model_validate(
            {
                **source_model_artifact.model_dump(mode="json"),
                "promoted": candidate_promoted,
                "promotion_reason": (
                    "held-out release gates passed"
                    if candidate_promoted
                    else "held-out release gates failed; prior baseline retained"
                ),
                "evaluation_report_id": report.report_id,
                "source_model_artifact_sha256": source_model_artifact_checksum,
                "selected_training_run_manifest_sha256": training_manifest_checksum,
                "evaluation_report_sha256": report_checksum,
            }
        )
        final_model_artifact_path = release_dir / "candidate-model-artifact.json"
        final_model_artifact_path.write_text(
            final_model_artifact.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        artifact_checksums = {
            name: f"sha256:{sha256_file(release_dir / name)}"
            for name in (
                "candidate-model-artifact.json",
                "evaluation-report.json",
                "evaluation-provenance.json",
                "curated-queries.json",
                "public-evidence.json",
                "LICENSE",
                "NOTICE",
            )
        }
        manifest = ReleaseManifest.model_validate(
            {
                "schema_version": "1.0.0",
                "release_id": report.report_id,
                "promoted_model_id": promoted_id,
                "dataset_manifest_hash": str(
                    evaluation_summary["result"].get("dataset_manifest_hash", "sha256:" + "0" * 64)
                ),
                "split_manifest_hash": str(provenance["split_manifest_hash"]),
                "evaluation_report_id": report.report_id,
                "git_sha": str(provenance["evaluation_git_sha"]),
                "evidence_mode": "verified",
                "provenance": {
                    "training": training_provenance.model_dump(mode="json"),
                    "evaluation": evaluation_provenance.model_dump(mode="json"),
                },
                "artifact_checksums": artifact_checksums,
                "models": models,
            }
        ).model_dump(mode="json", exclude_none=True)
        manifest_path = release_dir / "release-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
        ServiceState._validate_evidence_binding(public_evidence, manifest)
        bundle_checksums_path = _write_bundle_checksums(release_dir)
        _verify_bundle_checksum_inventory(release_dir)
        os.replace(release_dir, final_release_dir)
        release_dir = final_release_dir
        manifest_path = release_dir / "release-manifest.json"
        public_evidence_path = release_dir / public_evidence_path.name
        bundle_checksums_path = release_dir / bundle_checksums_path.name
        run.add_artifact("release_manifest", manifest_path)
        run.add_artifact("evaluation_report", release_dir / "evaluation-report.json")
        run.add_artifact("evaluation_provenance", release_dir / "evaluation-provenance.json")
        run.add_artifact("candidate_model_artifact", release_dir / "candidate-model-artifact.json")
        run.add_artifact("curated_queries", release_dir / "curated-queries.json")
        run.add_artifact("public_evidence", public_evidence_path)
        run.add_artifact("bundle_checksums", bundle_checksums_path)
        _success(
            run,
            {
                "release_id": report.report_id,
                "release_manifest": str(manifest_path.resolve()),
                "public_evidence": str(public_evidence_path.resolve()),
                "bundle_checksums": str(bundle_checksums_path.resolve()),
                "candidate_model_artifact": str(
                    (release_dir / "candidate-model-artifact.json").resolve()
                ),
                "promoted_model_id": promoted_id,
                "candidate_promoted": report.release_gate_results.passed,
                "split_manifest_hash": str(provenance["split_manifest_hash"]),
            },
        )
    except (OSError, StopIteration, KeyError, ValueError, ValidationError, RuntimeError) as error:
        _abort(run, error)


@app.command("serve")
def serve(
    model_manifest: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
) -> None:
    """Serve a checksum-verified release bundle and its static interface."""

    configure_logging()
    release_dir = model_manifest.resolve().parent
    settings = ServiceSettings(
        release_manifest=model_manifest.resolve(),
        curated_queries=release_dir / "curated-queries.json",
        public_evidence=release_dir / "public-evidence.json",
        release_mode=True,
    )
    uvicorn.run(create_app(settings), host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
