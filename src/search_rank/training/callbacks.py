"""Framework-independent early stopping and curve persistence."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CurvePoint:
    epoch: int
    optimizer_step: int
    training_loss: float
    validation_ndcg_at_10: float


class EarlyStopper:
    def __init__(self, patience: int, min_delta: float = 0.0) -> None:
        if patience < 1:
            raise ValueError("patience must be positive")
        if not math.isfinite(min_delta) or min_delta < 0:
            raise ValueError("min_delta must be finite and non-negative")
        self.patience = patience
        self.min_delta = min_delta
        self.best = float("-inf")
        self.patience_reference = float("-inf")
        self.bad_epochs = 0

    def update(self, value: float) -> tuple[bool, bool]:
        if not math.isfinite(value):
            raise ValueError("early-stopping metric must be finite")
        checkpoint_improved = value > self.best
        if checkpoint_improved:
            self.best = value
        materially_improved = value > self.patience_reference + self.min_delta
        if materially_improved:
            self.patience_reference = value
            self.bad_epochs = 0
        else:
            self.bad_epochs += 1
        return checkpoint_improved, self.bad_epochs >= self.patience


def write_curves(path: str | Path, points: list[CurvePoint]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([asdict(point) for point in points], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output
