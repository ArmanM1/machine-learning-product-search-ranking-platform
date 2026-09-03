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
    assert "LICENSE NOTICE" in text
    if filename == "Dockerfile.serve":
        assert 'ENTRYPOINT ["/opt/search-rank-venv/bin/python", "-m", "awslambdaric"]' in text
        assert 'CMD ["search_rank.serving.app.handler"]' in text
        assert "ARG VITE_DATA_MODE=api" in text
        assert 'test "${VITE_DATA_MODE}" = "api"' in text
        assert 'c.data_mode!=="api"' in text
    else:
        assert "ENTRYPOINT" in text
    if filename == "Dockerfile.train":
        assert 'ENTRYPOINT ["python", "/app/scripts/container_train.py"]' in text
        assert "SEARCH_RANK_CHECKPOINT_DIR=/opt/ml/checkpoints" in text


def test_ci_executes_installed_training_cli_and_attests_api_mode() -> None:
    pull_request = (ROOT / ".github/workflows/pull-request.yml").read_text(encoding="utf-8")
    deploy = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert '--entrypoint python "${image}" -m search_rank.cli --help' in pull_request
    assert '"${image}" train --help' not in pull_request
    for name in (
        "VITE_DATA_MODE",
        "VITE_API_BASE_URL",
        "VITE_PUBLIC_RUN_ID",
        "VITE_DEFAULT_QUERY_ID",
        "VITE_BASELINE_MODEL_ID",
        "VITE_CANDIDATE_MODEL_ID",
    ):
        assert f'--build-arg {name}="${{{name}}}"' in deploy
    assert '"${container_id}:/var/task/web/dist/build-config.json"' in deploy
    assert '.data_mode == "api"' in deploy


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
    if kind == "train":
        probe = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            tag,
            "-m",
            "search_rank.cli",
            "--help",
        ]
    elif kind == "eval":
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
