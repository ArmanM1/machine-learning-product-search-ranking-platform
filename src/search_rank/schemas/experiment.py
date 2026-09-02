"""Versioned experiment configuration contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, SchemaVersion, Sha256


class EarlyStoppingConfig(ContractModel):
    enabled: bool
    patience: Annotated[int, Field(ge=1)] = 2
    min_delta: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0


class ExperimentConfig(ContractModel):
    """All inputs needed to reproduce one model-training experiment."""

    schema_version: SchemaVersion
    config_id: NonEmptyStr
    config_hash: Sha256
    seed: Annotated[int, Field(ge=0, le=2**32 - 1)]
    dataset_manifest_hash: Sha256
    input_template_version: Literal["title_v1", "enriched_v1"]
    base_model_id: NonEmptyStr
    base_model_revision: NonEmptyStr
    base_model_license: NonEmptyStr
    max_sequence_length: Annotated[int, Field(ge=1)]
    loss_name: Literal["BinaryCrossEntropyLoss"]
    label_mapping_version: Literal["project_graded_v1"]
    sampling_strategy: Literal["mixed_hard_random_v1", "random_only_v1"]
    hard_example_sources: list[Literal["bm25", "pretrained_cross_encoder"]]
    learning_rate: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    effective_batch_size: Annotated[int, Field(ge=1)]
    gradient_accumulation_steps: Annotated[int, Field(ge=1)]
    max_epochs: Annotated[int, Field(ge=1)]
    warmup_ratio: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    early_stopping: EarlyStoppingConfig | bool
    precision: Literal["float32", "float16", "bfloat16", "fp32", "fp16", "bf16", "auto"]
    deterministic_mode: bool
    requested_hardware: NonEmptyStr

    @model_validator(mode="after")
    def sampling_sources_match_strategy(self) -> ExperimentConfig:
        sources = set(self.hard_example_sources)
        if len(sources) != len(self.hard_example_sources):
            raise ValueError("hard_example_sources must be unique")
        if self.sampling_strategy == "mixed_hard_random_v1" and sources != {
            "bm25",
            "pretrained_cross_encoder",
        }:
            raise ValueError("mixed sampling requires both declared unchanged baselines")
        if self.sampling_strategy == "random_only_v1" and sources:
            raise ValueError("random-only sampling must not declare hard-example sources")
        return self


__all__ = ["EarlyStoppingConfig", "ExperimentConfig"]
