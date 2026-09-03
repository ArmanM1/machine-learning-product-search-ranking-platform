from __future__ import annotations

import json
from pathlib import Path

from search_rank.runs import CommandRun

GIT_SHA = "a" * 40


def _finish(tmp_path: Path) -> dict[str, object]:
    run = CommandRun("container-test", None, output_root=tmp_path / "runs")
    summary = run.finish(status="completed")
    return json.loads(summary.read_text(encoding="utf-8"))


def test_command_summary_uses_workflow_bound_commit_without_git(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SEARCH_RANK_GIT_SHA", GIT_SHA)
    monkeypatch.setenv("SEARCH_RANK_LATEST_ROOT", str(tmp_path / "latest"))
    monkeypatch.setattr(
        "search_rank.runs.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("git")),
    )

    payload = _finish(tmp_path)

    assert payload["git_sha"] == GIT_SHA
    assert payload["repository_dirty"] is False


def test_command_summary_degrades_truthfully_when_git_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SEARCH_RANK_GIT_SHA", raising=False)
    monkeypatch.setenv("SEARCH_RANK_LATEST_ROOT", str(tmp_path / "latest"))
    monkeypatch.setattr(
        "search_rank.runs.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("git")),
    )

    payload = _finish(tmp_path)

    assert payload["git_sha"] == "unavailable"
    assert payload["repository_dirty"] is True
