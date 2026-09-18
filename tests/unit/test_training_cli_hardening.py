from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

import search_rank.cli as cli
from search_rank.training import TrainingRuntime


def _validation_error() -> ValidationError:
    return ValidationError.from_exception_data(
        "Fixture",
        [{"type": "missing", "loc": ("required",), "input": {}}],
    )


def _experiment(*, hard_sources: list[str]) -> Any:
    return SimpleNamespace(
        requested_hardware="local-test-cpu",
        base_model_id="fixture-model",
        base_model_revision="fixture-revision",
        max_sequence_length=16,
        input_template_version="enriched_v1",
        hard_example_sources=hard_sources,
        dataset_manifest_hash="sha256:" + "a" * 64,
    )


def test_device_preflight_runs_before_any_dataset_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequence: list[str] = []
    experiment = _experiment(hard_sources=[])

    def preflight(_: Any, *, device: str) -> TrainingRuntime:
        sequence.append(f"preflight:{device}")
        return TrainingRuntime(
            device="cpu",
            device_type="cpu",
            cuda_available=False,
            cuda_device_count=0,
            accelerator_type="cpu",
        )

    def load_manifest(_: Path) -> Any:
        sequence.append("data_load")
        raise ValueError("stop after proving order")

    class ExpectedStop(Exception):
        pass

    monkeypatch.delenv("SEARCH_RANK_HARDWARE_CLASS", raising=False)
    monkeypatch.delenv("SEARCH_RANK_ACCELERATOR", raising=False)
    monkeypatch.setattr(cli, "load_frozen_experiment", lambda _: experiment)
    monkeypatch.setattr(cli, "preflight_training_runtime", preflight)
    monkeypatch.setattr(cli, "load_dataset_manifest", load_manifest)
    monkeypatch.setattr(cli, "_abort", lambda _run, _error: (_ for _ in ()).throw(ExpectedStop))

    with pytest.raises(ExpectedStop):
        cli.train(Path("experiment.yaml"), Path("manifest.json"))

    assert sequence == ["preflight:auto", "data_load"]


@pytest.mark.parametrize(
    ("error_factory", "category"),
    (
        (lambda: OSError("private/path"), "io_failure"),
        (lambda: ValueError("private/path"), "contract_violation"),
        (_validation_error, "contract_violation"),
        (lambda: RuntimeError("private/path"), "runtime_failure"),
        (lambda: AssertionError("private/path"), "contract_violation"),
    ),
)
def test_all_caught_preflight_errors_write_bounded_managed_diagnostic(
    error_factory: Any,
    category: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = tmp_path / "output" / "failure"
    monkeypatch.setenv("SEARCH_RANK_TRAINING_FAILURE_PATH", str(failure))
    monkeypatch.setenv("SEARCH_RANK_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("SEARCH_RANK_LATEST_ROOT", str(tmp_path / "latest"))
    monkeypatch.setattr(
        cli,
        "load_frozen_experiment",
        lambda _: (_ for _ in ()).throw(error_factory()),
    )

    with pytest.raises(cli.typer.Exit):
        cli.train(Path("private-config-path.yaml"), Path("private-manifest-path.json"))

    assert failure.read_text(encoding="utf-8") == (
        f"phase=device_preflight; error_type={category}; exit_code=1\n"
    )
    summaries = "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "private/path" not in summaries
    assert "private-config-path" not in failure.read_text(encoding="utf-8")


def test_mining_cross_encoder_receives_resolved_device_and_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor: dict[str, Any] = {}
    released: list[tuple[object, str]] = []
    model = object()

    def cross_encoder(*args: Any, **kwargs: Any) -> object:
        constructor["args"] = args
        constructor["kwargs"] = kwargs
        return model

    monkeypatch.setattr(cli, "CrossEncoder", cross_encoder)
    monkeypatch.setattr(cli, "rank_cross_encoder", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        cli,
        "release_cross_encoder_resources",
        lambda selected, *, device_type: released.append((selected, device_type)),
    )

    records = cli._training_mining_records(
        pd.DataFrame(),
        _experiment(hard_sources=["pretrained_cross_encoder"]),
        text_column="text_enriched_v1",
        device="cuda:0",
        device_type="cuda",
    )

    assert records == []
    assert constructor["kwargs"]["device"] == "cuda:0"
    assert constructor["kwargs"]["trust_remote_code"] is False
    assert released == [(model, "cuda")]


def test_mining_model_is_released_when_ranking_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = object()
    released: list[object] = []
    monkeypatch.setattr(cli, "CrossEncoder", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(
        cli,
        "rank_cross_encoder",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ranking failed")),
    )
    monkeypatch.setattr(
        cli,
        "release_cross_encoder_resources",
        lambda selected, *, device_type: released.append(selected),
    )

    with pytest.raises(RuntimeError, match="ranking failed"):
        cli._training_mining_records(
            pd.DataFrame(),
            _experiment(hard_sources=["pretrained_cross_encoder"]),
            text_column="text_enriched_v1",
            device="cpu",
            device_type="cpu",
        )

    assert released == [model]
