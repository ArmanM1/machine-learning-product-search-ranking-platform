"""Streaming, checksum-enforced public dataset acquisition."""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

from search_rank.artifacts.checksums import sha256_file, verify_file
from search_rank.logging import log_event

from .settings import DataPreparationConfig, SourceFile

LOGGER = logging.getLogger(__name__)


def _download_one(source: SourceFile, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            verify_file(destination, source.sha256)
            if destination.stat().st_size != source.size_bytes:
                raise ValueError("size mismatch")
            log_event(LOGGER, "dataset_file_reused", file=destination.name)
            return destination
        except ValueError:
            destination.unlink()

    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        str(source.url),
        headers={"User-Agent": "search-rank/0.1 dataset-acquisition"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            while chunk := response.read(8 * 1024 * 1024):
                out.write(chunk)
        if partial.stat().st_size != source.size_bytes:
            raise ValueError(
                f"size mismatch for {source.filename}: expected {source.size_bytes}, "
                f"got {partial.stat().st_size}"
            )
        actual = sha256_file(partial)
        if actual != source.sha256:
            raise ValueError(
                f"checksum mismatch for {source.filename}: expected {source.sha256}, got {actual}"
            )
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    log_event(LOGGER, "dataset_file_downloaded", file=destination.name, bytes=source.size_bytes)
    return destination


def acquire_dataset(config: DataPreparationConfig) -> dict[str, Path]:
    return {
        name: _download_one(source, config.raw_dir / source.filename)
        for name, source in config.sources.items()
    }
