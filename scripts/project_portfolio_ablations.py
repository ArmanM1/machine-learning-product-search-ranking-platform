#!/usr/bin/env python3
"""Project a private frozen trial selection into strict public ablation evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from search_rank.schemas.portfolio import (
    PortfolioAblationContrast,
    PortfolioAblationEvidence,
    PortfolioAblationTrial,
)
from search_rank.schemas.trial import TrialSelection


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("trial selection contains duplicate JSON keys")
        result[key] = value
    return result


def project(selection_path: Path) -> PortfolioAblationEvidence:
    """Validate the private source and return only explicitly allowlisted fields."""

    if not selection_path.is_file() or selection_path.is_symlink():
        raise ValueError("trial selection must be a regular file")
    source = selection_path.read_bytes()
    try:
        payload = json.loads(source, object_pairs_hook=_reject_duplicates)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("trial selection is not canonical JSON") from error
    selection = TrialSelection.model_validate(payload)
    trials = [
        PortfolioAblationTrial(
            role=trial.role,
            promotion_eligible=trial.promotion_eligible,
            model_id=trial.candidate_model_id,
            config_id=trial.config_id,
            config_sha256=trial.candidate_training_config_sha256,
            input_template_version=trial.input_template_version,
            sampling_strategy=trial.sampling_strategy,
            hard_example_sources=list(trial.hard_example_sources),
            validation_graded_ndcg_at_10=trial.best_validation_ndcg_at_10,
        )
        for trial in selection.trials
    ]
    contrasts = [
        PortfolioAblationContrast(
            contrast_id=contrast.contrast_id,
            control_role=contrast.control_role,
            controlled_difference_fields=list(contrast.controlled_difference_fields),
            treatment_validation_graded_ndcg_at_10=(contrast.treatment_validation_ndcg_at_10),
            control_validation_graded_ndcg_at_10=contrast.control_validation_ndcg_at_10,
            treatment_minus_control=contrast.treatment_minus_control,
        )
        for contrast in selection.contrasts
    ]
    return PortfolioAblationEvidence(
        schema_version="1.0.0",
        artifact_type="portfolio_ablation_evidence",
        source_trial_selection_sha256="sha256:" + hashlib.sha256(source).hexdigest(),
        selection_id=selection.selection_id,
        git_sha=selection.git_sha,
        dataset_manifest_sha256=selection.dataset_manifest_hash,
        metric=selection.metric_name,
        test_access_count=selection.test_access_count,
        selected_model_id=selection.selected_candidate_model_id,
        selected_config_sha256=selection.selected_candidate_config_sha256,
        trials=trials,
        contrasts=contrasts,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = project(args.selection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(args.output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
