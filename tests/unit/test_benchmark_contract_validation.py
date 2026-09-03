from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_benchmark_contracts import (
    _DURABLE_FILES,
    _sha256,
    _validate_local_inventory,
    _validate_published_inventory,
)
from search_rank.schemas.evidence import BundleChecksums


def _bundle(tmp_path: Path) -> tuple[BundleChecksums, Path]:
    for name in sorted(_DURABLE_FILES):
        (tmp_path / name).write_text(f'{{"artifact":"{name}"}}\n', encoding="utf-8")
    inventory = BundleChecksums.model_validate(
        {
            "schema_version": "1.0.0",
            "files": {name: _sha256(tmp_path / name) for name in sorted(_DURABLE_FILES)},
        }
    )
    path = tmp_path / "evidence-checksums.json"
    path.write_text(inventory.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return inventory, path


def test_benchmark_inventory_rejects_any_changed_durable_bytes(tmp_path: Path) -> None:
    inventory, _ = _bundle(tmp_path)
    _validate_local_inventory(tmp_path, inventory)

    (tmp_path / "cost-preflight.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum differs"):
        _validate_local_inventory(tmp_path, inventory)


def test_published_inventory_requires_exact_content_addressed_prefix_and_keys(
    tmp_path: Path,
) -> None:
    _, inventory_path = _bundle(tmp_path)
    digest = _sha256(inventory_path).removeprefix("sha256:")
    prefix = f"public/release-1/performance/runs/github-123-attempt-1/sha256-{digest}/"
    object_list = tmp_path / "published.json"
    expected_names = _DURABLE_FILES | {"evidence-checksums.json"}
    object_list.write_text(
        json.dumps(
            {
                "IsTruncated": False,
                "Contents": [{"Key": prefix + name} for name in sorted(expected_names)],
            }
        ),
        encoding="utf-8",
    )
    _validate_published_inventory(
        object_list,
        prefix=prefix,
        release_id="release-1",
        benchmark_run_id="github-123-attempt-1",
        inventory_path=inventory_path,
    )

    with pytest.raises(ValueError, match="run- and content-addressed"):
        _validate_published_inventory(
            object_list,
            prefix="public/release-1/performance/latest/",
            release_id="release-1",
            benchmark_run_id="github-123-attempt-1",
            inventory_path=inventory_path,
        )

    payload = json.loads(object_list.read_text(encoding="utf-8"))
    payload["Contents"].pop()
    object_list.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="inventory is not exact"):
        _validate_published_inventory(
            object_list,
            prefix=prefix,
            release_id="release-1",
            benchmark_run_id="github-123-attempt-1",
            inventory_path=inventory_path,
        )
