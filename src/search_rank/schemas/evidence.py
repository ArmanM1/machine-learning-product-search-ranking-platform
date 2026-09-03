"""Contracts for immutable release and evaluation evidence files."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .api import ModelSummary, PublicEvaluationProvenance, PublicTrainingProvenance
from .common import ContractModel, NonEmptyStr, Sha256

GitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{7,64}$", min_length=7, max_length=64)]
EvaluationGitSha = Annotated[str, Field(pattern=r"^(?:unavailable|[0-9a-f]{7,64})$")]
EvaluationImageDigest = Annotated[str, Field(pattern=r"^(?:unavailable|sha256:[0-9a-f]{64})$")]
RelativeArtifactPath = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$", min_length=1, max_length=512),
]
Count = Annotated[int, Field(ge=0)]
UnitFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]


def _assert_safe_relative_path(value: str) -> None:
    if value.startswith("/") or "\\" in value or "//" in value:
        raise ValueError("artifact paths must be normalized relative POSIX paths")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("artifact paths cannot contain empty, dot, or parent segments")


class BundleChecksums(ContractModel):
    """Complete content-addressed inventory excluding the inventory itself."""

    schema_version: Literal["1.0.0"]
    files: dict[RelativeArtifactPath, Sha256]

    @model_validator(mode="after")
    def paths_are_safe_and_inventory_is_not_recursive(self) -> BundleChecksums:
        if not self.files:
            raise ValueError("checksum inventory cannot be empty")
        for path in self.files:
            _assert_safe_relative_path(path)
        if "bundle-checksums.json" in self.files or "evidence-checksums.json" in self.files:
            raise ValueError("checksum inventory cannot include itself")
        return self


class ReleaseModel(ContractModel):
    """One executable model entry in a release bundle."""

    model_id: NonEmptyStr
    kind: Literal["bm25", "pretrained", "fine_tuned"]
    checkpoint: RelativeArtifactPath | None = None
    text_template: Literal["title_v1", "enriched_v1"]
    artifact_checksum: Sha256
    batch_size: Annotated[int, Field(ge=1, le=1024)] | None = None
    public_summary: ModelSummary

    @model_validator(mode="after")
    def executable_fields_and_public_summary_match(self) -> ReleaseModel:
        if self.kind == "bm25":
            if self.checkpoint is not None or self.batch_size is not None:
                raise ValueError("BM25 entries cannot declare checkpoint or batch size")
        elif self.checkpoint is None or self.batch_size is None:
            raise ValueError("neural model entries require checkpoint and batch size")
        if self.checkpoint is not None:
            _assert_safe_relative_path(self.checkpoint)
        if (
            self.public_summary.model_id != self.model_id
            or self.public_summary.kind != self.kind
            or self.public_summary.artifact_checksum != self.artifact_checksum
        ):
            raise ValueError("model public summary differs from its executable entry")
        return self


class ReleaseExecutionProvenance(ContractModel):
    training: PublicTrainingProvenance
    evaluation: PublicEvaluationProvenance

    @model_validator(mode="after")
    def selected_training_artifact_is_the_evaluated_candidate(
        self,
    ) -> ReleaseExecutionProvenance:
        if self.training.selected_model_id != self.evaluation.candidate_model_id:
            raise ValueError("training selection and evaluated candidate differ")
        if (
            self.training.selected_model_artifact_checksum
            != self.evaluation.candidate_model_artifact_checksum
        ):
            raise ValueError("training and evaluation model checksums differ")
        if self.training.git_sha != self.evaluation.git_sha:
            raise ValueError("training and evaluation commits differ")
        return self


class ReleaseManifest(ContractModel):
    """Typed executable and provenance manifest for one immutable public bundle."""

    schema_version: Literal["1.0.0"]
    release_id: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$", min_length=3, max_length=100)
    ]
    promoted_model_id: NonEmptyStr
    dataset_manifest_hash: Sha256
    split_manifest_hash: Sha256
    evaluation_report_id: NonEmptyStr
    git_sha: GitSha
    evidence_mode: Literal["validation_only", "verified"]
    provenance: ReleaseExecutionProvenance | None = None
    artifact_checksums: dict[RelativeArtifactPath, Sha256]
    models: Annotated[list[ReleaseModel], Field(min_length=2)]

    @model_validator(mode="after")
    def release_is_complete_and_promotion_is_bound(self) -> ReleaseManifest:
        model_ids = [model.model_id for model in self.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("release model IDs must be unique")
        if self.promoted_model_id not in model_ids:
            raise ValueError("promoted model is absent from release models")
        by_id = {model.model_id: model for model in self.models}
        for path in self.artifact_checksums:
            _assert_safe_relative_path(path)
        expected_files = {
            "curated-queries.json",
            "public-evidence.json",
            "LICENSE",
            "NOTICE",
        }
        if self.evidence_mode == "validation_only":
            expected_files.add("baseline-summary.json")
            if self.provenance is not None:
                raise ValueError("validation-only releases cannot claim held-out provenance")
            if any(model.kind == "fine_tuned" for model in self.models):
                raise ValueError("validation-only bootstrap cannot contain a fine-tuned candidate")
        else:
            expected_files.update(
                {
                    "candidate-model-artifact.json",
                    "evaluation-report.json",
                    "evaluation-provenance.json",
                }
            )
            if self.provenance is None:
                raise ValueError("verified releases require training and evaluation provenance")
            if self.provenance.training.git_sha != self.git_sha:
                raise ValueError("release Git SHA differs from execution provenance")
            candidate_id = self.provenance.training.selected_model_id
            candidate = by_id.get(candidate_id)
            if candidate is None or candidate.kind != "fine_tuned":
                raise ValueError("verified release lacks the selected fine-tuned candidate")
            if (
                candidate.artifact_checksum
                != self.provenance.training.selected_model_artifact_checksum
            ):
                raise ValueError("release candidate checksum differs from training provenance")
        if set(self.artifact_checksums) != expected_files:
            raise ValueError("release artifact checksum inventory is not exact")
        for model in self.models:
            if model.public_summary.evaluation_report_id != self.evaluation_report_id:
                raise ValueError("model summary references a different evaluation report")
        promoted = next(model for model in self.models if model.model_id == self.promoted_model_id)
        if promoted.public_summary.promoted_at is None:
            raise ValueError("promoted model summary must record promoted_at")
        if any(
            model.model_id != self.promoted_model_id
            and model.public_summary.promoted_at is not None
            for model in self.models
        ):
            raise ValueError("only the active model may record promoted_at")
        return self


class SourceEvaluation(ContractModel):
    run_id: NonEmptyStr
    report_id: NonEmptyStr
    report_checksum: Sha256
    provenance_checksum: Sha256
    test_access_count: Annotated[int, Field(ge=1)]
    candidate_metric: UnitFloat
    candidate_ranking_hash: Sha256


class EvaluationProvenance(ContractModel):
    """Internal, immutable provenance for one clean run or its two-run binding."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["evaluation_provenance"]
    report_id: NonEmptyStr
    split: Literal["validation", "test"]
    config_hash: Sha256
    evaluation_config_checksum: Sha256
    staged_evaluation_config_checksum: Sha256
    evaluation_image_digest: EvaluationImageDigest
    evaluation_git_sha: EvaluationGitSha
    hardware_class: Literal["local-cpu", "ml.m5.xlarge"]
    region: Literal["local", "us-east-1"]
    training_strategy: Literal["mixed_hard_random_v1", "random_only_v1"]
    frozen_config: NonEmptyStr
    checkpoint_checksum: Sha256
    dataset_manifest_hash: Sha256
    split_manifest_hash: Sha256
    dataset_name: NonEmptyStr
    dataset_version: NonEmptyStr
    dataset_locale: Literal["us"]
    strongest_baseline_id: NonEmptyStr
    validation_baseline_summary_checksum: Sha256
    candidate_universe_hash: Sha256
    system_universe_hashes: dict[NonEmptyStr, Sha256]
    candidate_lists_aligned: Literal[True]
    clean_run_metric_values: list[UnitFloat]
    clean_ranking_hashes: list[Sha256]
    independent_evaluation_count: Literal[1, 2]
    slice_min_query_count: Annotated[int, Field(ge=1)]
    reproduction_tolerance: NonNegativeFloat
    evaluated_baseline_model_ids: Annotated[list[NonEmptyStr], Field(min_length=1)]
    test_access_count: Count
    source_evaluations: list[SourceEvaluation]

    @model_validator(mode="after")
    def clean_execution_inventory_is_exact(self) -> EvaluationProvenance:
        count = self.independent_evaluation_count
        if len(self.clean_run_metric_values) != count or len(self.clean_ranking_hashes) != count:
            raise ValueError("clean metric/ranking inventories must equal execution count")
        if len(self.evaluated_baseline_model_ids) != len(set(self.evaluated_baseline_model_ids)):
            raise ValueError("evaluated baseline model IDs must be unique")
        if self.strongest_baseline_id not in self.evaluated_baseline_model_ids:
            raise ValueError("strongest baseline is absent from the evaluated baselines")
        if self.split == "validation":
            if self.test_access_count != 0:
                raise ValueError("validation provenance cannot record held-out access")
        else:
            if self.test_access_count < count:
                raise ValueError("held-out access count cannot be below clean execution count")
            if (
                self.evaluation_image_digest == "unavailable"
                or self.evaluation_git_sha == "unavailable"
            ):
                raise ValueError("held-out provenance requires immutable image and Git identities")
            if self.hardware_class == "local-cpu" or self.region == "local":
                raise ValueError("held-out provenance requires cloud execution identity")
        if count == 1:
            if self.source_evaluations:
                raise ValueError("a single clean execution cannot contain bound sources")
        else:
            if len(self.source_evaluations) != 2:
                raise ValueError("a bound evaluation requires exactly two source evaluations")
            if len(set(self.clean_ranking_hashes)) != 1:
                raise ValueError("bound clean evaluations must have identical candidate rankings")
            sources = sorted(self.source_evaluations, key=lambda item: item.test_access_count)
            if sources[1].test_access_count != sources[0].test_access_count + 1:
                raise ValueError("bound source test-access counts must be consecutive")
            if sources[1].test_access_count != self.test_access_count:
                raise ValueError("bound test-access count must equal the latest source")
            if len({source.run_id for source in sources}) != 2:
                raise ValueError("bound sources must be distinct clean runs")
            if [source.candidate_metric for source in sources] != self.clean_run_metric_values:
                raise ValueError("bound source metrics differ from clean_run_metric_values")
            if [source.candidate_ranking_hash for source in sources] != self.clean_ranking_hashes:
                raise ValueError("bound source rankings differ from clean_ranking_hashes")
        if any(not math.isfinite(value) for value in self.clean_run_metric_values):
            raise ValueError("clean metrics must be finite")
        return self


__all__ = [
    "BundleChecksums",
    "EvaluationProvenance",
    "ReleaseExecutionProvenance",
    "ReleaseManifest",
    "ReleaseModel",
    "SourceEvaluation",
]
