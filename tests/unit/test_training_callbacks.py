from __future__ import annotations

from pathlib import Path

import pytest

from search_rank.training.callbacks import CurvePoint, EarlyStopper, write_curves
from search_rank.training.trainer import _schedule_factor


def test_early_stopper_tracks_best_and_patience() -> None:
    stopper = EarlyStopper(patience=2, min_delta=0.01)
    assert stopper.update(0.50) == (True, False)
    # A literal new best is checkpointed even when it is too small to reset patience.
    assert stopper.update(0.505) == (True, False)
    assert stopper.update(0.50) == (False, True)
    assert stopper.best == 0.505
    assert stopper.patience_reference == 0.50


def test_early_stopper_resets_patience_only_after_min_delta() -> None:
    stopper = EarlyStopper(patience=2, min_delta=0.01)
    stopper.update(0.50)
    stopper.update(0.505)
    assert stopper.update(0.511) == (True, False)
    assert stopper.patience_reference == 0.511
    assert stopper.bad_epochs == 0


def test_early_stopper_rejects_non_finite_metrics() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        EarlyStopper(patience=2).update(float("nan"))


@pytest.mark.parametrize(
    ("step", "warmup_steps", "total_steps", "expected"),
    [
        (0, 2, 10, 0.5),
        (1, 2, 10, 1.0),
        (2, 2, 10, 1.0),
        (6, 2, 10, 0.5),
        (10, 2, 10, 0.0),
        (0, 0, 10, 1.0),
        (5, 0, 10, 0.5),
    ],
)
def test_warmup_and_linear_decay_schedule(
    step: int,
    warmup_steps: int,
    total_steps: int,
    expected: float,
) -> None:
    assert _schedule_factor(
        step, warmup_steps=warmup_steps, total_steps=total_steps
    ) == pytest.approx(expected)


def test_curves_are_machine_readable(tmp_path: Path) -> None:
    path = write_curves(tmp_path / "curves.json", [CurvePoint(1, 2, 0.3, 0.8)])
    assert '"validation_ndcg_at_10": 0.8' in path.read_text(encoding="utf-8")
