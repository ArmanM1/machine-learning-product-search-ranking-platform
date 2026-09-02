from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = ("Dockerfile.train", "Dockerfile.eval", "Dockerfile.serve")


@pytest.mark.parametrize("filename", DOCKERFILES)
def test_container_contract_is_digest_pinned_and_non_root(filename: str) -> None:
    text = (ROOT / filename).read_text(encoding="utf-8")
    from_lines = [line for line in text.splitlines() if line.startswith("FROM ")]
    assert from_lines
    assert all("@sha256:" in line for line in from_lines)
    assert all("latest" not in line.casefold() for line in from_lines)
    assert "USER ${APP_UID}:${APP_GID}" in text
    assert "USER root" not in text
    if filename == "Dockerfile.serve":
        assert 'CMD ["search_rank.serving.app.handler"]' in text
    else:
        assert "ENTRYPOINT" in text


@pytest.mark.slow
@pytest.mark.parametrize("filename", DOCKERFILES)
def test_container_builds_and_executes_documented_probe(filename: str) -> None:
    if os.environ.get("RUN_CONTAINER_TESTS") != "1":
        pytest.skip("set RUN_CONTAINER_TESTS=1 for the multi-gigabyte image build checks")
    if shutil.which("docker") is None:
        pytest.skip("Docker is unavailable")
    kind = filename.removeprefix("Dockerfile.")
    tag = f"search-rank-{kind}:integration"
    subprocess.run(
        ["docker", "build", "--file", filename, "--tag", tag, "."],
        cwd=ROOT,
        check=True,
        timeout=1800,
    )
    if kind in {"train", "eval"}:
        probe = ["docker", "run", "--rm", tag, "--help"]
    else:
        probe = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            tag,
            "-c",
            "import os, search_rank.serving.app; assert os.geteuid() != 0",
        ]
    subprocess.run(probe, cwd=ROOT, check=True, timeout=180)
