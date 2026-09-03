#!/usr/bin/env python3
"""Plan and verify exact active-root S3 keys without ever touching release archives."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}$")


class StaticRootManifestError(ValueError):
    """A local or remote static-root inventory is unsafe or not exact."""


def source_keys(root: Path) -> list[str]:
    if not root.is_dir():
        raise StaticRootManifestError("static source root does not exist")
    keys = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    if not keys or "index.html" not in keys:
        raise StaticRootManifestError("static source must contain index.html")
    if len(keys) != len(set(keys)):
        raise StaticRootManifestError("static source keys are not unique")
    for key in keys:
        if (
            SAFE_KEY.fullmatch(key) is None
            or key.startswith("releases/")
            or ".." in key.split("/")
            or "//" in key
        ):
            raise StaticRootManifestError("static source contains an unsafe key")
    return keys


def inventory_keys(path: Path) -> tuple[list[str], list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StaticRootManifestError("S3 inventory is unavailable or invalid") from exc
    if not isinstance(payload, dict) or payload.get("IsTruncated") is True:
        raise StaticRootManifestError("S3 inventory is incomplete")
    contents = payload.get("Contents", [])
    if not isinstance(contents, list) or len(contents) > 10_000:
        raise StaticRootManifestError("S3 inventory has an invalid size")
    active: list[str] = []
    releases: list[str] = []
    for item in contents:
        key = item.get("Key") if isinstance(item, dict) else None
        if not isinstance(key, str) or SAFE_KEY.fullmatch(key) is None or "//" in key:
            raise StaticRootManifestError("S3 inventory contains an unsafe key")
        if key.startswith("releases/"):
            releases.append(key)
        else:
            active.append(key)
    if len(active) != len(set(active)) or len(releases) != len(set(releases)):
        raise StaticRootManifestError("S3 inventory contains duplicate keys")
    return sorted(active), sorted(releases)


def stale_keys(root: Path, inventory: Path) -> list[str]:
    expected = set(source_keys(root))
    active, _ = inventory_keys(inventory)
    return sorted(set(active) - expected)


def verify_exact(root: Path, inventory: Path) -> None:
    expected = source_keys(root)
    active, releases = inventory_keys(inventory)
    if active != expected:
        raise StaticRootManifestError("active static root differs from the exact source manifest")
    if not releases:
        raise StaticRootManifestError("immutable release archives unexpectedly disappeared")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--source-root", type=Path, required=True)
    plan.add_argument("--inventory", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--source-root", type=Path, required=True)
    verify.add_argument("--inventory", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            args.output.write_text(
                json.dumps(stale_keys(args.source_root, args.inventory), indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            verify_exact(args.source_root, args.inventory)
    except (OSError, StaticRootManifestError) as exc:
        raise SystemExit(f"static root manifest rejected: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
