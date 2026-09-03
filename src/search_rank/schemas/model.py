"""Immutable trained-model artifact contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, Sha256, UtcDateTime

Count = Annotated[int, Field(ge=0)]
UnitFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
ArtifactGitSha = Annotated[str, Field(pattern=r"^(?:unavailable|[0-9a-f]{7,64})$")]
ArtifactImageDigest = Annotated[str, Field(pattern=r"^(?:unavailable|sha256:[0-9a-f]{64})$")]


class TrainingSampleStatistics(ContractModel):
    """Auditable composition of the exact sample used for training."""

    row_count: Annotated[int, Field(ge=1)]
    sampling_source_counts: dict[NonEmptyStr, Count]
    label_counts: dict[NonEmptyStr, Count]

    @model_validator(mode="after")
    def counts_cover_the_sample(self) -> TrainingSampleStatistics:
        if sum(self.sampling_source_counts.values()) != self.row_count:
            raise ValueError("sampling-source counts must sum to row_count")
        if sum(self.label_counts.values()) != self.row_count:
            raise ValueError("label counts must sum to row_count")
        return self


class TrainingResultEvidence(ContractModel):
    """Portable subset of the trainer result; paths are bundle-relative."""

    best_checkpoint: Literal["candidate/best"]
    best_validation_ndcg_at_10: UnitFloat
    epochs_completed: Annotated[int, Field(ge=1)]
    optimizer_steps: Annotated[int, Field(ge=1)]
    duration_seconds: NonNegativeFloat
    changed_parameter_count: Annotated[int, Field(ge=1)]
    curves_path: Literal["candidate/curves.json"]
    fresh_load_verified: Literal[True]
    warmup_steps: Count
    planned_optimizer_steps: Annotated[int, Field(ge=1)]
    device_type: Literal["cpu", "cuda", "mps"]
    cuda_available: bool
    cuda_device_count: Count
    accelerator_type: Literal["cpu", "gpu"]

    @model_validator(mode="after")
    def completed_steps_do_not_exceed_plan(self) -> TrainingResultEvidence:
        if self.optimizer_steps > self.planned_optimizer_steps:
            raise ValueError("optimizer_steps cannot exceed planned_optimizer_steps")
        if self.warmup_steps > self.planned_optimizer_steps:
            raise ValueError("warmup_steps cannot exceed planned_optimizer_steps")
        if self.cuda_available != (self.cuda_device_count > 0):
            raise ValueError("CUDA availability and device count differ")
        if (self.device_type == "cuda") != (self.accelerator_type == "gpu"):
            raise ValueError("actual training device and accelerator differ")
        if self.device_type == "cuda" and not self.cuda_available:
            raise ValueError("CUDA execution requires an available CUDA device")
        return self


class ModelArtifact(ContractModel):
    """The real model-manifest emitted with every training result.

    A training job records the truthful pre-evaluation promotion placeholders
    required by the PRD. A later immutable promotion-time copy may bind the
    final held-out decision and evaluation report.
    """

    schema_version: Literal["1.0.0"]
    model_id: NonEmptyStr
    run_id: NonEmptyStr
    base_model_id: NonEmptyStr
    base_model_revision: NonEmptyStr
    tokenizer_revision: NonEmptyStr
    checkpoint_uri: Literal["candidate/best"]
    artifact_checksum: Sha256
    artifact_size_bytes: Annotated[int, Field(ge=1)]
    config_id: NonEmptyStr
    config_hash: Sha256
    dataset_manifest_hash: Sha256
    input_contract_version: Literal["title_v1", "enriched_v1"]
    label_mapping_version: Literal["project_graded_v1"]
    sampling_strategy: Literal["mixed_hard_random_v1", "random_only_v1"]
    hard_example_sources: list[Literal["bm25", "pretrained_cross_encoder"]]
    promoted: bool
    promotion_reason: NonEmptyStr
    evaluation_report_id: NonEmptyStr
    git_sha: ArtifactGitSha = "unavailable"
    image_digest: ArtifactImageDigest = "unavailable"
    source_model_artifact_sha256: Sha256 | None = None
    selected_training_run_manifest_sha256: Sha256 | None = None
    evaluation_report_sha256: Sha256 | None = None
    sample_statistics: TrainingSampleStatistics
    training_result: TrainingResultEvidence
    created_at: UtcDateTime

    @model_validator(mode="after")
    def provenance_is_internally_consistent(self) -> ModelArtifact:
        sources = set(self.hard_example_sources)
        if len(sources) != len(self.hard_example_sources):
            raise ValueError("hard-example sources must be unique")
        if self.sampling_strategy == "mixed_hard_random_v1" and sources != {
            "bm25",
            "pretrained_cross_encoder",
        }:
            raise ValueError("mixed sampling must name both hard-example sources")
        if self.sampling_strategy == "random_only_v1" and sources:
            raise ValueError("random-only sampling cannot name hard-example sources")
        if self.checkpoint_uri != self.training_result.best_checkpoint:
            raise ValueError("checkpoint_uri must match the portable trainer result")
        final_bindings = (
            self.source_model_artifact_sha256,
            self.selected_training_run_manifest_sha256,
            self.evaluation_report_sha256,
        )
        if self.evaluation_report_id == "not_evaluated":
            if self.promoted or self.promotion_reason != "pending held-out evaluation":
                raise ValueError("unevaluated artifacts must record the pending, unpromoted state")
            if any(value is not None for value in final_bindings):
                raise ValueError("unevaluated artifacts cannot claim final release bindings")
        else:
            if any(value is None for value in final_bindings):
                raise ValueError(
                    "evaluated artifacts require source, run-manifest, and report hashes"
                )
            if self.git_sha == "unavailable" or self.image_digest == "unavailable":
                raise ValueError("evaluated artifacts require exact training source identity")
            expected_reason = (
                "held-out release gates passed"
                if self.promoted
                else "held-out release gates failed; prior baseline retained"
            )
            if self.promotion_reason != expected_reason:
                raise ValueError("final promotion reason does not match the held-out decision")
        return self


__all__ = [
    "ModelArtifact",
    "TrainingResultEvidence",
    "TrainingSampleStatistics",
]
