"""Strict configuration contracts used by command-line workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Bm25Config(StrictConfig):
    k1: float = Field(gt=0)
    b: float = Field(ge=0, le=1)
    tokenizer: str


class CrossEncoderConfig(StrictConfig):
    model_config_path: Path = Field(alias="model_config")
    batch_size: int = Field(ge=1, le=512)
    device: str = "auto"


class BaselineRunConfig(StrictConfig):
    schema_version: str
    config_id: str
    dataset_manifest: Path
    split: Literal["train", "validation", "development"]
    input_templates: list[Literal["title_v1", "enriched_v1"]]
    systems: list[Literal["input_order", "seeded_random", "bm25", "pretrained_cross_encoder"]]
    random_seed: int = Field(ge=0, le=2**32 - 1)
    bm25: Bm25Config
    cross_encoder: CrossEncoderConfig


class EvaluationRunConfig(StrictConfig):
    schema_version: str
    split: Literal["validation", "test"]
    requires_heldout_guard: bool = False
    bootstrap_resamples: int = Field(ge=1)
    bootstrap_seed: int = Field(ge=0, le=2**32 - 1)
    confidence_level: float = Field(gt=0, lt=1)
    metric_definition_version: Literal["project_graded_v1"]
    reproduction_tolerance: float = Field(default=0.002, ge=0)
    slice_min_query_count: int = Field(ge=1)
    dataset_manifest: Path = Path("data/processed/esci-us-v1/current.json")
    candidate_summary: Path = Path("artifacts/latest/train.json")
    baseline_summary: Path = Path("artifacts/latest/baseline-run.json")
    strongest_baseline_id: str | None = None


__all__ = ["BaselineRunConfig", "EvaluationRunConfig"]
