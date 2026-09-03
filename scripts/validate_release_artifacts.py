#!/usr/bin/env python3
"""Pydantic-validate every durable JSON release artifact before publication."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, RootModel

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from search_rank.artifacts.checksums import sha256_file
from search_rank.command_config import BaselineRunConfig
from search_rank.config import sha256_value, validate_config
from search_rank.schemas.api import PublicEvidenceEnvelope
from search_rank.schemas.dataset import DatasetManifest
from search_rank.schemas.evaluation import EvaluationReport
from search_rank.schemas.evidence import BundleChecksums, EvaluationProvenance, ReleaseManifest
from search_rank.schemas.model import ModelArtifact
from search_rank.schemas.publication import (
    BaselineSummary,
    CommandSummary,
    CuratedQueryCollection,
    HeldoutAccessCounter,
    ProcessingJobEvidence,
    PublicationEvidence,
    ReleaseSummary,
    TrialSelectionBinding,
    TrialSelectionVerification,
)
from search_rank.schemas.release import PromotionPointer
from search_rank.schemas.run import RunManifest
from search_rank.schemas.trial import TrialSelection
from search_rank.schemas.workflow import (
    CandidateReleaseInputs,
    EvaluationCostPreflight,
    SageMakerProcessingQuotaPreflight,
)


class JsonObject(RootModel[dict[str, Any]]):
    """Object-root JSON for third-party model support files without project semantics."""


MODELS: dict[str, type[BaseModel]] = {
    "access-counter": HeldoutAccessCounter,
    "baseline-summary": BaselineSummary,
    "bundle-checksums": BundleChecksums,
    "candidate-release-inputs": CandidateReleaseInputs,
    "command-summary": CommandSummary,
    "curated-queries": CuratedQueryCollection,
    "dataset-manifest": DatasetManifest,
    "evaluation-cost-preflight": EvaluationCostPreflight,
    "evaluation-provenance": EvaluationProvenance,
    "evaluation-report": EvaluationReport,
    "model-artifact": ModelArtifact,
    "processing-job-evidence": ProcessingJobEvidence,
    "processing-quota-preflight": SageMakerProcessingQuotaPreflight,
    "promotion-pointer": PromotionPointer,
    "publication-evidence": PublicationEvidence,
    "public-evidence": PublicEvidenceEnvelope,
    "release-manifest": ReleaseManifest,
    "release-summary": ReleaseSummary,
    "run-manifest": RunManifest,
    "trial-selection": TrialSelection,
    "trial-selection-binding": TrialSelectionBinding,
    "trial-selection-verification": TrialSelectionVerification,
}

ROOT_ARTIFACTS = {
    "baseline-summary.json": "baseline-summary",
    "bundle-checksums.json": "bundle-checksums",
    "candidate-model-artifact.json": "model-artifact",
    "curated-queries.json": "curated-queries",
    "evaluation-provenance.json": "evaluation-provenance",
    "evaluation-report.json": "evaluation-report",
    "public-evidence.json": "public-evidence",
    "release-manifest.json": "release-manifest",
}


def validate_file(path: Path, kind: str) -> None:
    model = MODELS[kind]
    model.model_validate_json(path.read_text(encoding="utf-8"))


def validate_bundle(root: Path) -> None:
    from scripts.verify_release import verify_release

    verify_release(root, load_models=False)
    for path in sorted(root.rglob("*.json")):
        relative = path.relative_to(root).as_posix()
        if path.parent == root:
            kind = ROOT_ARTIFACTS.get(path.name)
            if kind is None:
                raise ValueError(f"unrecognized root release JSON artifact: {relative}")
            validate_file(path, kind)
        elif relative.startswith("models/"):
            JsonObject.model_validate_json(path.read_text(encoding="utf-8"))
        else:
            raise ValueError(f"unrecognized nested release JSON artifact: {relative}")


def validate_frozen_baseline_evidence(
    *,
    command_summary_path: Path,
    baseline_summary_path: Path,
    baseline_config_path: Path,
    baseline_config_file_sha256: str,
    baseline_summary_sha256: str,
    expected_git_sha: str,
    dataset_manifest_hash: str,
    strongest_baseline_id: str,
    baseline_ids: tuple[str, ...],
) -> str:
    """Bind validation baseline bytes to the current clean evaluator/config revision."""

    if re.fullmatch(r"[0-9a-f]{40}", expected_git_sha) is None:
        raise ValueError("expected baseline Git revision must be a full commit SHA")
    if re.fullmatch(r"[0-9a-f]{64}", baseline_config_file_sha256) is None:
        raise ValueError("baseline config file checksum must be lowercase SHA-256 hex")
    if re.fullmatch(r"[0-9a-f]{64}", baseline_summary_sha256) is None:
        raise ValueError("baseline summary checksum must be lowercase SHA-256 hex")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", dataset_manifest_hash) is None:
        raise ValueError("baseline dataset identity must be a canonical SHA-256")
    if not baseline_ids or len(baseline_ids) != len(set(baseline_ids)):
        raise ValueError("baseline IDs must be non-empty and unique")
    if strongest_baseline_id not in baseline_ids:
        raise ValueError("strongest baseline is absent from the declared baseline IDs")
    if sha256_file(baseline_config_path) != baseline_config_file_sha256:
        raise ValueError("checked-out baseline config bytes differ from the dispatch")
    if sha256_file(baseline_summary_path) != baseline_summary_sha256:
        raise ValueError("baseline summary bytes differ from the dispatch")

    command = CommandSummary.model_validate_json(command_summary_path.read_text(encoding="utf-8"))
    baseline = BaselineSummary.model_validate_json(
        baseline_summary_path.read_text(encoding="utf-8")
    )
    validated_config = validate_config(baseline_config_path, BaselineRunConfig)
    semantic_config_hash = f"sha256:{sha256_value(validated_config)}"
    expected_artifact_hash = f"sha256:{baseline_summary_sha256}"
    expected_config_parts = PurePosixPath(baseline_config_path.as_posix()).parts

    if command.command != "baseline-run" or command.status != "succeeded":
        raise ValueError("baseline command evidence is not a successful baseline-run")
    if command.git_sha != expected_git_sha:
        raise ValueError("baseline command was produced by a different Git revision")
    if command.repository_dirty:
        raise ValueError("baseline command was produced from a dirty repository")
    command_config_parts = (
        PurePosixPath(command.config_path.replace("\\", "/")).parts
        if command.config_path is not None
        else ()
    )
    if (
        ".." in command_config_parts
        or len(command_config_parts) < len(expected_config_parts)
        or command_config_parts[-len(expected_config_parts) :] != expected_config_parts
    ):
        raise ValueError("baseline command references a different config path")

    ranking_names = tuple(f"ranking_{index:02d}" for index in range(len(baseline.rankings)))
    expected_artifacts = {"baseline_summary", "curated_queries", *ranking_names}
    if set(command.artifact_paths) != expected_artifacts:
        raise ValueError("baseline command artifact inventory is not exact")
    if command.result.get("baseline_summary") != command.artifact_paths["baseline_summary"]:
        raise ValueError("baseline command result and artifact path differ: baseline_summary")
    if command.result.get("curated_queries") != command.artifact_paths["curated_queries"]:
        raise ValueError("baseline command result and artifact path differ: curated_queries")
    if len(set(baseline.rankings.values())) != len(baseline.rankings):
        raise ValueError("baseline summary ranking paths must be unique")
    for index, model_id in enumerate(sorted(baseline.rankings)):
        name = f"ranking_{index:02d}"
        if command.artifact_paths[name] != baseline.rankings[model_id]:
            raise ValueError(f"baseline command ranking path differs from summary: {name}")
    for name in sorted(expected_artifacts):
        available_path = Path(command.artifact_paths[name])
        if available_path.is_file() and command.artifact_hashes[name] != (
            f"sha256:{sha256_file(available_path)}"
        ):
            raise ValueError(f"available baseline command artifact checksum mismatch: {name}")

    if command.artifact_hashes.get("baseline_summary") != expected_artifact_hash:
        raise ValueError("baseline command does not bind the exact baseline summary bytes")

    expected_result = {
        "config_hash": semantic_config_hash,
        "dataset_checksum": dataset_manifest_hash,
        "strongest_baseline_id": strongest_baseline_id,
        "metrics": baseline.metrics,
        "resumed_from_run_id": baseline.resumed_from_run_id,
    }
    for field, expected in expected_result.items():
        if field not in command.result or command.result[field] != expected:
            raise ValueError(f"baseline command result differs from frozen evidence: {field}")
    if baseline.config_hash != semantic_config_hash:
        raise ValueError("baseline summary differs from the checked-out baseline config")
    if baseline.dataset_manifest_hash != dataset_manifest_hash:
        raise ValueError("baseline summary differs from the frozen dataset identity")
    if baseline.strongest_baseline_id != strongest_baseline_id:
        raise ValueError("baseline summary differs from the frozen strongest baseline")
    if set(baseline.metrics) != set(baseline_ids):
        raise ValueError("baseline summary metric inventory differs from declared baseline IDs")
    return semantic_config_hash


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    file_parser = subparsers.add_parser("file")
    file_parser.add_argument("path", type=Path)
    file_parser.add_argument("--kind", required=True, choices=sorted(MODELS))
    bundle_parser = subparsers.add_parser("bundle")
    bundle_parser.add_argument("root", type=Path)
    baseline_parser = subparsers.add_parser("baseline-evidence")
    baseline_parser.add_argument("--command-summary", type=Path, required=True)
    baseline_parser.add_argument("--baseline-summary", type=Path, required=True)
    baseline_parser.add_argument("--baseline-config", type=Path, required=True)
    baseline_parser.add_argument("--baseline-config-file-sha256", required=True)
    baseline_parser.add_argument("--baseline-summary-sha256", required=True)
    baseline_parser.add_argument("--expected-git-sha", required=True)
    baseline_parser.add_argument("--dataset-manifest-hash", required=True)
    baseline_parser.add_argument("--strongest-baseline-id", required=True)
    baseline_parser.add_argument("--baseline-ids", required=True)
    args = parser.parse_args()
    if args.command == "file":
        validate_file(args.path, args.kind)
    elif args.command == "bundle":
        validate_bundle(args.root)
    else:
        semantic_hash = validate_frozen_baseline_evidence(
            command_summary_path=args.command_summary,
            baseline_summary_path=args.baseline_summary,
            baseline_config_path=args.baseline_config,
            baseline_config_file_sha256=args.baseline_config_file_sha256,
            baseline_summary_sha256=args.baseline_summary_sha256,
            expected_git_sha=args.expected_git_sha,
            dataset_manifest_hash=args.dataset_manifest_hash,
            strongest_baseline_id=args.strongest_baseline_id,
            baseline_ids=tuple(args.baseline_ids.split(",")),
        )
        print(semantic_hash)


if __name__ == "__main__":
    main()
