from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import static_root_manifest


def _write_inventory(path: Path, keys: list[str]) -> None:
    path.write_text(
        json.dumps({"IsTruncated": False, "Contents": [{"Key": key} for key in keys]}),
        encoding="utf-8",
    )


def test_plan_deletes_only_stale_active_keys_and_never_release_archives(tmp_path: Path) -> None:
    source = tmp_path / "dist"
    source.mkdir()
    (source / "index.html").write_text("new", encoding="utf-8")
    (source / "assets").mkdir()
    (source / "assets/app-new.js").write_text("new", encoding="utf-8")
    inventory = tmp_path / "inventory.json"
    _write_inventory(
        inventory,
        [
            "index.html",
            "assets/app-new.js",
            "assets/app-old.js",
            "releases/old/index.html",
            "releases/new/index.html",
        ],
    )

    assert static_root_manifest.stale_keys(source, inventory) == ["assets/app-old.js"]


def test_verify_requires_exact_active_manifest_and_preserved_releases(tmp_path: Path) -> None:
    source = tmp_path / "dist"
    source.mkdir()
    (source / "index.html").write_text("new", encoding="utf-8")
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, ["index.html", "releases/new/index.html"])

    static_root_manifest.verify_exact(source, inventory)

    _write_inventory(inventory, ["index.html", "stale.js", "releases/new/index.html"])
    with pytest.raises(static_root_manifest.StaticRootManifestError, match="differs"):
        static_root_manifest.verify_exact(source, inventory)


def test_unsafe_or_truncated_inventory_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "dist"
    source.mkdir()
    (source / "index.html").write_text("new", encoding="utf-8")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps({"IsTruncated": True, "Contents": [{"Key": "../escape"}]}),
        encoding="utf-8",
    )

    with pytest.raises(static_root_manifest.StaticRootManifestError):
        static_root_manifest.stale_keys(source, inventory)
