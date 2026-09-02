"""Predictable, redacted command summaries for local and cloud entry points."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from search_rank.artifacts.checksums import sha256_file
from search_rank.schemas.public import redact_for_public


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def new_run_id(command: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{command.replace(' ', '-')}-{stamp}-{uuid.uuid4().hex[:8]}"


@dataclass
class CommandRun:
    """Track one command and always leave an actionable machine-readable summary."""

    command: str
    config_path: str | None
    output_root: Path = field(
        default_factory=lambda: Path(os.environ.get("SEARCH_RANK_RUN_ROOT", "artifacts/runs"))
    )
    run_id: str = field(init=False)
    started_at: datetime = field(init=False)
    started_clock: float = field(init=False)
    artifacts: dict[str, str] = field(default_factory=dict)
    checksums: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.run_id = new_run_id(self.command)
        self.started_at = datetime.now(UTC)
        self.started_clock = time.perf_counter()

    @property
    def run_dir(self) -> Path:
        return self.output_root / self.run_id

    def add_artifact(self, name: str, path: str | Path) -> None:
        artifact = Path(path).resolve()
        self.artifacts[name] = str(artifact)
        if artifact.is_file():
            self.checksums[name] = f"sha256:{sha256_file(artifact)}"

    def finish(
        self,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        failure: str | None = None,
    ) -> Path:
        ended = datetime.now(UTC)
        payload = {
            "schema_version": "1.0.0",
            "run_id": self.run_id,
            "command": self.command,
            "status": status,
            "config_path": str(Path(self.config_path).resolve()) if self.config_path else None,
            "started_at": self.started_at.isoformat(),
            "ended_at": ended.isoformat(),
            "duration_seconds": time.perf_counter() - self.started_clock,
            "git_sha": _git("rev-parse", "HEAD"),
            "repository_dirty": bool(_git("status", "--porcelain")),
            "runtime": {"python": platform.python_version(), "platform": platform.platform()},
            "artifact_paths": self.artifacts,
            "artifact_hashes": self.checksums,
            "result": result or {},
            "failure": failure,
        }
        public_payload = redact_for_public(payload)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        summary = self.run_dir / "summary.json"
        summary.write_text(
            json.dumps(public_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        latest_root = Path(os.environ.get("SEARCH_RANK_LATEST_ROOT", "artifacts/latest"))
        latest = latest_root / f"{self.command.replace(' ', '-')}.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(
            json.dumps(
                {"run_id": self.run_id, "summary": str(summary.resolve())},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return summary


__all__ = ["CommandRun", "new_run_id"]
