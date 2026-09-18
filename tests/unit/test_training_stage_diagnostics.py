from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import torch

import search_rank.training.diagnostics as diagnostics
from scripts import container_train, sanitize_training_failure
from search_rank.training.diagnostics import (
    FAILURE_CATEGORIES,
    FAILURE_DIAGNOSTIC_ENV,
    TRAINING_STAGES,
    TrainingStageFailure,
    categorize_training_failure,
    training_stage,
)


def test_stage_and_category_allowlists_match_container_and_sanitizer() -> None:
    assert TRAINING_STAGES == container_train._TRAINING_PHASES
    assert TRAINING_STAGES <= sanitize_training_failure._PHASES
    assert FAILURE_CATEGORIES == container_train._FAILURE_CATEGORIES
    assert FAILURE_CATEGORIES <= sanitize_training_failure._ERROR_TYPES


@pytest.mark.parametrize("stage", sorted(TRAINING_STAGES))
def test_managed_stage_failure_contains_only_allowlisted_facts(
    stage: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = tmp_path / "output" / "failure"
    private_message = "s3://private-bucket/account/123 user@example.com"
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setenv(FAILURE_DIAGNOSTIC_ENV, str(failure))
    monkeypatch.setattr(
        diagnostics,
        "log_event",
        lambda _logger, event, **context: events.append((event, context)),
    )

    with pytest.raises(TrainingStageFailure) as captured, training_stage(stage):
        raise RuntimeError(private_message)

    assert str(captured.value) == f"phase={stage}; error_type=runtime_failure"
    assert failure.read_text(encoding="utf-8") == (
        f"phase={stage}; error_type=runtime_failure; exit_code=1\n"
    )
    assert private_message not in str(captured.value)
    assert private_message not in failure.read_text(encoding="utf-8")
    assert events == [
        ("training_stage", {"stage": stage, "status": "started"}),
        (
            "training_stage",
            {"stage": stage, "status": "failed", "error_type": "runtime_failure"},
        ),
    ]
    assert not ({"path", "run_id", "job_id", "account_id", "input"} & events[-1][1].keys())


def test_local_stage_preserves_original_exception_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FAILURE_DIAGNOSTIC_ENV, raising=False)
    original = ValueError("actionable local detail")

    with (
        pytest.raises(ValueError, match="actionable local detail") as captured,
        training_stage("sampling"),
    ):
        raise original

    assert captured.value is original


@pytest.mark.parametrize(
    ("error", "category"),
    (
        (MemoryError(), "resource_exhausted"),
        (torch.cuda.OutOfMemoryError(), "resource_exhausted"),
        (PermissionError(), "permission_denied"),
        (FileNotFoundError(), "io_failure"),
        (ModuleNotFoundError(), "dependency_failure"),
        (ValueError(), "contract_violation"),
        (RuntimeError(), "runtime_failure"),
        (Exception(), "unexpected_failure"),
    ),
)
def test_exception_categories_do_not_depend_on_messages(
    error: Exception,
    category: str,
) -> None:
    assert categorize_training_failure(error) == category


def test_success_breadcrumb_has_no_execution_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.delenv(FAILURE_DIAGNOSTIC_ENV, raising=False)
    monkeypatch.setattr(
        diagnostics,
        "log_event",
        lambda _logger, event, **context: events.append((event, context)),
    )

    with training_stage("data_load"):
        pass

    assert events == [
        ("training_stage", {"stage": "data_load", "status": "started"}),
        ("training_stage", {"stage": "data_load", "status": "succeeded"}),
    ]


def test_nested_same_stage_emits_one_breadcrumb_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.delenv(FAILURE_DIAGNOSTIC_ENV, raising=False)
    monkeypatch.setattr(
        diagnostics,
        "log_event",
        lambda _logger, event, **context: events.append((event, context)),
    )

    with training_stage("device_preflight"), training_stage("device_preflight"):
        pass

    assert events == [
        ("training_stage", {"stage": "device_preflight", "status": "started"}),
        ("training_stage", {"stage": "device_preflight", "status": "succeeded"}),
    ]
