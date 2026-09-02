from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from search_rank.artifacts.checksums import sha256_file
from search_rank.baselines.bm25 import rank_bm25, tokenize
from search_rank.baselines.common import write_rankings
from search_rank.baselines.input_order import rank_input_order
from search_rank.baselines.random_order import rank_seeded_random
from search_rank.cli import _resume_baseline_rankings
from search_rank.command_config import BaselineRunConfig


def candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "query_id": "q1",
                "query": "red running shoe",
                "product_id": "p2",
                "source_index": 2,
                "esci_label": "Irrelevant",
                "text_enriched_v1": "Title: blue cup",
            },
            {
                "query_id": "q1",
                "query": "red running shoe",
                "product_id": "p1",
                "source_index": 1,
                "esci_label": "Exact",
                "text_enriched_v1": "Title: red running shoe",
            },
        ]
    )


def test_bm25_prefers_lexical_match() -> None:
    ranked = rank_bm25(candidates())
    assert [record.product_id for record in ranked] == ["p1", "p2"]
    assert tokenize("Red-shoe") == ["red", "shoe"]


def test_input_order_is_source_index_order() -> None:
    assert [record.product_id for record in rank_input_order(candidates())] == ["p1", "p2"]


def test_seeded_random_is_reproducible() -> None:
    left = rank_seeded_random(candidates(), seed=42)
    right = rank_seeded_random(candidates().iloc[::-1], seed=42)
    assert [(item.product_id, item.score) for item in left] == [
        (item.product_id, item.score) for item in right
    ]


def test_failed_report_can_resume_only_checksum_verified_complete_rankings(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "baselines.yaml"
    config_path.write_text("fixture\n", encoding="utf-8")
    config = BaselineRunConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "config_id": "fixture",
            "dataset_manifest": tmp_path / "manifest.json",
            "split": "validation",
            "input_templates": ["enriched_v1"],
            "systems": ["input_order", "seeded_random"],
            "random_seed": 42,
            "bm25": {"k1": 1.5, "b": 0.75, "tokenizer": "fixture"},
            "cross_encoder": {
                "model_config": tmp_path / "model.yaml",
                "batch_size": 2,
                "device": "cpu",
            },
        }
    )
    ranking_dir = tmp_path / "rankings"
    paths = [
        write_rankings(ranking_dir / "00.jsonl", rank_input_order(candidates())),
        write_rankings(ranking_dir / "01.jsonl", rank_seeded_random(candidates(), seed=42)),
    ]
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "run_id": "baseline-run-failed",
                "command": "baseline-run",
                "status": "failed",
                "config_path": str(config_path.resolve()),
                "artifact_paths": {
                    f"ranking_{index:02d}": str(path.resolve()) for index, path in enumerate(paths)
                },
                "artifact_hashes": {
                    f"ranking_{index:02d}": f"sha256:{sha256_file(path)}"
                    for index, path in enumerate(paths)
                },
            }
        ),
        encoding="utf-8",
    )

    rankings, source_run = _resume_baseline_rankings(
        summary_path,
        config_path=config_path,
        config=config,
        frame=candidates(),
    )
    assert source_run == "baseline-run-failed"
    assert set(rankings) == {"input-order-v1", "seeded-random-v1-seed-42"}

    with paths[0].open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        _resume_baseline_rankings(
            summary_path,
            config_path=config_path,
            config=config,
            frame=candidates(),
        )
