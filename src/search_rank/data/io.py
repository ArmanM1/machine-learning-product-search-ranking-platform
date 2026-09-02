"""Checksum-enforced prepared artifact access with a held-out fail-closed boundary."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from search_rank.artifacts.checksums import verify_file
from search_rank.config import sha256_value
from search_rank.evaluation.gates import HeldoutAccessDenied
from search_rank.schemas.dataset import DatasetManifest

if TYPE_CHECKING:
    from search_rank.evaluation.gates import HeldoutAccessReceipt


SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _checksum_index(manifest_path: Path) -> dict[str, str]:
    checksums_path = manifest_path.parent / "artifact-checksums.json"
    payload = json.loads(checksums_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("prepared artifact checksum index must be a non-empty object")
    checksums = {str(name): str(checksum) for name, checksum in payload.items()}
    if any(not SHA256.fullmatch(checksum) for checksum in checksums.values()):
        raise ValueError("prepared artifact checksum index contains a non-canonical SHA-256")
    return checksums


def _verify_dataset_identity(manifest: DatasetManifest, manifest_path: Path) -> None:
    checksums = _checksum_index(manifest_path)
    calculated = f"sha256:{sha256_value({'preprocessing_version': manifest.preprocessing_version, 'artifacts': {name: checksum.removeprefix('sha256:') for name, checksum in checksums.items()}})}"
    if calculated != manifest.processed_checksum:
        raise ValueError("prepared artifact index does not match the manifest processed checksum")


def resolve_manifest_path(reference: str | Path) -> Path:
    path = Path(reference)
    if path.is_dir():
        path = path / "manifest.json"
    if path.name == "current.json":
        if not path.is_file():
            raise FileNotFoundError(f"prepared-data pointer not found: {path}")
        pointer = json.loads(path.read_text(encoding="utf-8"))
        referenced = Path(pointer["manifest"])
        path = referenced if referenced.is_absolute() else path.parent / referenced
    if not path.is_file():
        raise FileNotFoundError(f"dataset manifest not found: {path}")
    return path.resolve()


def load_dataset_manifest(reference: str | Path) -> tuple[DatasetManifest, Path]:
    reference_path = Path(reference)
    pointer_checksum: str | None = None
    if reference_path.name == "current.json" and reference_path.is_file():
        pointer = json.loads(reference_path.read_text(encoding="utf-8"))
        pointer_checksum = str(pointer.get("processed_checksum", ""))
    path = resolve_manifest_path(reference)
    manifest = DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if pointer_checksum is not None and pointer_checksum != manifest.processed_checksum:
        raise ValueError("prepared-data pointer checksum does not match its manifest")
    _verify_dataset_identity(manifest, path)
    return manifest, path


def load_prepared_split(
    reference: str | Path,
    split: str,
    *,
    heldout_receipt: HeldoutAccessReceipt | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    if split not in {"train", "validation", "test", "development"}:
        raise ValueError(f"unknown prepared split: {split}")
    if split == "test" and (heldout_receipt is None or not heldout_receipt.authorized):
        raise HeldoutAccessDenied(
            "held-out data cannot be opened without a validated release-workflow receipt"
        )
    manifest, manifest_path = load_dataset_manifest(reference)
    artifact_path = manifest_path.parent / f"{split}.parquet"
    checksums = _checksum_index(manifest_path)
    try:
        expected = checksums[artifact_path.name]
    except KeyError as exc:
        raise ValueError(f"missing checksum for prepared artifact: {artifact_path.name}") from exc
    verify_file(artifact_path, expected)
    return pd.read_parquet(artifact_path), manifest
