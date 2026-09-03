"""SageMaker-compatible, fail-closed entry point for the training image."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _discover_file(
    explicit: str | None,
    *,
    root: Path,
    preferred_names: tuple[str, ...],
    patterns: tuple[str, ...],
    label: str,
) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
        return path
    for name in preferred_names:
        preferred = root / name
        if preferred.is_file():
            return preferred.resolve()
    candidates = sorted(
        {candidate.resolve() for pattern in patterns for candidate in root.rglob(pattern)}
    )
    if not candidates:
        raise FileNotFoundError(f"no {label} found below {root}")
    if len(candidates) != 1:
        rendered = ", ".join(str(path) for path in candidates[:5])
        raise ValueError(
            f"multiple {label} files found below {root}; pass an explicit path: {rendered}"
        )
    return candidates[0]


def build_command(argv: list[str]) -> tuple[list[str], Path]:
    parser = argparse.ArgumentParser(
        description="Run one versioned candidate training job in a SageMaker training container."
    )
    parser.add_argument(
        "program",
        nargs="?",
        choices=("train",),
        help="SageMaker invokes custom training images as `docker run IMAGE train`.",
    )
    parser.add_argument("--config", help="Frozen candidate experiment YAML")
    parser.add_argument("--dataset-manifest", help="Prepared-data current.json or manifest.json")
    parser.add_argument(
        "--model-dir",
        default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"),
        help="SageMaker model output directory",
    )
    args = parser.parse_args(argv)

    config_root = Path(os.environ.get("SM_CHANNEL_CONFIG", "/opt/ml/input/data/config"))
    data_root = Path(os.environ.get("SM_CHANNEL_TRAINING", "/opt/ml/input/data/training"))
    config = _discover_file(
        args.config,
        root=config_root,
        preferred_names=("experiment.yaml", "candidate-v1.yaml", "experiment.yml"),
        patterns=("*.yaml", "*.yml"),
        label="frozen experiment configuration",
    )
    manifest = _discover_file(
        args.dataset_manifest,
        root=data_root,
        preferred_names=("manifest.json", "current.json"),
        patterns=("current.json", "manifest.json"),
        label="dataset manifest",
    )
    model_dir = Path(args.model_dir).expanduser().resolve()
    model_dir.mkdir(parents=True, exist_ok=True)
    frozen_config = model_dir / "frozen-experiment.yaml"
    shutil.copy2(config, frozen_config)
    command = [
        sys.executable,
        "-m",
        "search_rank.cli",
        "train",
        "--config",
        str(frozen_config),
        "--dataset-manifest",
        str(manifest),
    ]
    return command, model_dir


def main(argv: list[str] | None = None) -> int:
    try:
        command, model_dir = build_command(sys.argv[1:] if argv is None else argv)
        completed = subprocess.run(command, cwd=model_dir, check=False)
        return completed.returncode
    except (OSError, ValueError) as error:
        print(f"training container preflight failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
