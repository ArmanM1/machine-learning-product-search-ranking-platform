"""Content-addressing primitives."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: str | Path, expected: str) -> str:
    normalized = expected.removeprefix("sha256:").lower()
    actual = sha256_file(path)
    if actual != normalized:
        raise ValueError(
            f"checksum mismatch for {Path(path).name}: expected {normalized}, got {actual}"
        )
    return actual


def sha256_directory(path: str | Path) -> str:
    """Hash file names and contents in stable POSIX-path order."""

    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"artifact directory not found: {root}")
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(item).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
