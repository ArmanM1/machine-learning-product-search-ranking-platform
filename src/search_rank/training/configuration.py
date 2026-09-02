"""Freeze a human-readable experiment template into an immutable config."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from search_rank.config import config_hash_without_field, load_yaml
from search_rank.data.io import load_dataset_manifest
from search_rank.schemas.experiment import ExperimentConfig


def freeze_experiment_config(
    template_path: str | Path,
    *,
    dataset_manifest_path: str | Path,
    output_path: str | Path,
) -> ExperimentConfig:
    raw = load_yaml(template_path)
    manifest, _ = load_dataset_manifest(dataset_manifest_path)
    raw["dataset_manifest_hash"] = manifest.processed_checksum
    raw["config_hash"] = f"sha256:{config_hash_without_field(raw)}"
    config = ExperimentConfig.model_validate(raw)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    sidecar = output.with_suffix(output.suffix + ".json")
    sidecar.write_text(
        json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return config


def load_frozen_experiment(path: str | Path) -> ExperimentConfig:
    raw = load_yaml(path)
    config = ExperimentConfig.model_validate(raw)
    expected = f"sha256:{config_hash_without_field(raw)}"
    if config.config_hash != expected:
        raise ValueError(f"frozen configuration hash mismatch; expected {expected}")
    return config
