from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PYTORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def _read_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_linux_and_windows_torch_resolve_from_cpu_index() -> None:
    project = _read_toml(ROOT / "pyproject.toml")
    uv = project["tool"]["uv"]

    cpu_index = next(index for index in uv["index"] if index["name"] == "pytorch-cpu")
    assert cpu_index == {
        "name": "pytorch-cpu",
        "url": PYTORCH_CPU_INDEX,
        "explicit": True,
    }
    assert uv["sources"]["torch"] == [
        {
            "index": "pytorch-cpu",
            "marker": "sys_platform == 'linux' or sys_platform == 'win32'",
        }
    ]

    lock = _read_toml(ROOT / "uv.lock")
    packages = lock["package"]
    cpu_torch = [
        package
        for package in packages
        if package["name"] == "torch"
        and package["source"].get("registry") == PYTORCH_CPU_INDEX
    ]
    assert len(cpu_torch) == 1
    assert cpu_torch[0]["version"].endswith("+cpu")
    assert all(
        "sys_platform == 'linux'" in marker or "sys_platform == 'win32'" in marker
        for marker in cpu_torch[0]["resolution-markers"]
    )


def test_lock_excludes_gpu_only_torch_runtime_packages() -> None:
    lock = _read_toml(ROOT / "uv.lock")
    package_names = {package["name"] for package in lock["package"]}

    assert "triton" not in package_names
    assert not {name for name in package_names if name.startswith(("cuda-", "nvidia-"))}
