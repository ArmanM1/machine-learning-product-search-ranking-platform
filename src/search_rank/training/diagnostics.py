"""Privacy-safe stage reporting for managed candidate training."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn

import torch

from search_rank.logging import log_event

LOGGER = logging.getLogger(__name__)

TrainingStage = Literal[
    "device_preflight",
    "data_load",
    "mining",
    "sampling",
    "artifact_write",
    "trainer_init",
    "epoch",
    "post_train",
]

TRAINING_STAGES: frozenset[str] = frozenset(
    {
        "device_preflight",
        "data_load",
        "mining",
        "sampling",
        "artifact_write",
        "trainer_init",
        "epoch",
        "post_train",
    }
)
FAILURE_CATEGORIES: frozenset[str] = frozenset(
    {
        "contract_violation",
        "dependency_failure",
        "io_failure",
        "permission_denied",
        "resource_exhausted",
        "runtime_failure",
        "unexpected_failure",
    }
)
FAILURE_DIAGNOSTIC_ENV = "SEARCH_RANK_TRAINING_FAILURE_PATH"
_ACTIVE_STAGE: ContextVar[TrainingStage | None] = ContextVar(
    "search_rank_training_stage",
    default=None,
)


class TrainingStageFailure(RuntimeError):
    """A redacted managed-training failure with only allowlisted fields."""

    def __init__(self, stage: TrainingStage, error_type: str) -> None:
        if stage not in TRAINING_STAGES:
            raise ValueError("unsupported training failure stage")
        if error_type not in FAILURE_CATEGORIES:
            raise ValueError("unsupported training failure category")
        self.stage = stage
        self.error_type = error_type
        super().__init__(f"phase={stage}; error_type={error_type}")


def categorize_training_failure(error: Exception) -> str:
    """Map an exception to a stable category without inspecting its message."""

    if isinstance(error, MemoryError | torch.cuda.OutOfMemoryError):
        return "resource_exhausted"
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, OSError):
        return "io_failure"
    if isinstance(error, ImportError | ModuleNotFoundError):
        return "dependency_failure"
    if isinstance(error, AssertionError | KeyError | TypeError | ValueError):
        return "contract_violation"
    if isinstance(error, RuntimeError):
        return "runtime_failure"
    return "unexpected_failure"


def _diagnostic_path() -> Path | None:
    raw = os.environ.get(FAILURE_DIAGNOSTIC_ENV)
    return Path(raw) if raw else None


def _write_failure(stage: TrainingStage, error_type: str) -> bool:
    path = _diagnostic_path()
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"phase={stage}; error_type={error_type}; exit_code=1\n",
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


@dataclass
class TrainingStageTracker:
    """Track one active stage and redact failures only in managed containers."""

    stage: TrainingStage
    _active: bool = False

    def start(self) -> None:
        if self.stage not in TRAINING_STAGES:
            raise ValueError("unsupported training stage")
        self._active = True
        log_event(LOGGER, "training_stage", stage=self.stage, status="started")

    def transition(self, stage: TrainingStage) -> None:
        if stage not in TRAINING_STAGES:
            raise ValueError("unsupported training stage")
        if self._active:
            log_event(LOGGER, "training_stage", stage=self.stage, status="succeeded")
        self.stage = stage
        self._active = True
        log_event(LOGGER, "training_stage", stage=self.stage, status="started")

    def complete(self) -> None:
        if self._active:
            log_event(LOGGER, "training_stage", stage=self.stage, status="succeeded")
            self._active = False

    def fail(self, error: Exception) -> TrainingStageFailure | None:
        error_type = categorize_training_failure(error)
        log_event(
            LOGGER,
            "training_stage",
            stage=self.stage,
            status="failed",
            error_type=error_type,
        )
        self._active = False
        managed_diagnostic = _diagnostic_path() is not None
        _write_failure(self.stage, error_type)
        if managed_diagnostic:
            return TrainingStageFailure(self.stage, error_type)
        return None


@contextmanager
def training_stage(stage: TrainingStage) -> Iterator[None]:
    """Report a stage and redact its exception when a container path is configured."""

    if _ACTIVE_STAGE.get() == stage:
        yield
        return
    tracker = TrainingStageTracker(stage)
    tracker.start()
    token = _ACTIVE_STAGE.set(stage)
    try:
        yield
    except TrainingStageFailure:
        raise
    except Exception as error:
        redacted = tracker.fail(error)
        if redacted is not None:
            raise redacted from error
        raise
    else:
        tracker.complete()
    finally:
        _ACTIVE_STAGE.reset(token)


def fail_tracked_stage(tracker: TrainingStageTracker, error: Exception) -> NoReturn:
    """Raise a redacted cloud failure or preserve the original local exception."""

    redacted = tracker.fail(error)
    if redacted is not None:
        raise redacted from error
    raise error.with_traceback(error.__traceback__)


__all__ = [
    "FAILURE_CATEGORIES",
    "FAILURE_DIAGNOSTIC_ENV",
    "TRAINING_STAGES",
    "TrainingStage",
    "TrainingStageFailure",
    "TrainingStageTracker",
    "categorize_training_failure",
    "fail_tracked_stage",
    "training_stage",
]
