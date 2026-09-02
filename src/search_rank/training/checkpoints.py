"""Checkpoint loading and independent parameter-change verification."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import torch
from sentence_transformers import CrossEncoder


def snapshot_parameters(model: CrossEncoder) -> dict[str, torch.Tensor]:
    transformer = model.model
    if transformer is None:
        raise RuntimeError("cross-encoder has no underlying transformer model")
    return {name: value.detach().cpu().clone() for name, value in transformer.state_dict().items()}


def assert_any_parameter_changed(before: dict[str, torch.Tensor], model: CrossEncoder) -> list[str]:
    transformer = model.model
    if transformer is None:
        raise RuntimeError("cross-encoder has no underlying transformer model")
    current = transformer.state_dict()
    changed = [
        name for name, prior in before.items() if not torch.equal(prior, current[name].cpu())
    ]
    if not changed:
        raise AssertionError("candidate training did not change any parameters")
    return changed


def load_checkpoint(path: str | Path, *, device: str = "cpu") -> CrossEncoder:
    checkpoint = Path(path)
    if not checkpoint.is_dir():
        raise FileNotFoundError(f"checkpoint directory not found: {checkpoint}")
    return cast(
        CrossEncoder,
        CrossEncoder(str(checkpoint), device=device, trust_remote_code=False),
    )
