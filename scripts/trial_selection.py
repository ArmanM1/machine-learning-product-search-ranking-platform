#!/usr/bin/env python3
"""Build and verify the frozen three-run validation trial-selection artifact."""

from __future__ import annotations

import argparse
import json
import math
import tarfile
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from search_rank.artifacts.checksums import sha256_directory, sha256_file
from search_rank.config import sha256_value
from search_rank.schemas import RunManifest, TrialSelection
from search_rank.schemas.workflow import CandidateReleaseInputs
from search_rank.training.configuration import load_frozen_experiment

ROLES = ("candidate_treatment", "random_negative_control", "title_only_control")
ROLE_PATHS = {
    "candidate_treatment": "configs/experiments/candidate-v1.yaml",
    "random_negative_control": "configs/experiments/candidate-random-ablation-v1.yaml",
    "title_only_control": "configs/experiments/candidate-title-ablation-v1.yaml",
}
SELECTION_RULE = (
    "The enriched mixed-hard/random candidate treatment was preregistered as the only "
    "promotion-eligible model. The random-negative and title-only trials are validation-only "
    "single-factor controls and are never substituted based on their observed metric values."
)
RUN_MANIFEST_KEY_FIELDS = (
    "training_run_manifest_s3_key",
    "candidate_training_run_manifest_s3_key",
    "run_manifest_s3_key",
)
RUN_MANIFEST_HASH_FIELDS = (
    "training_run_manifest_sha256",
    "candidate_training_run_manifest_sha256",
    "run_manifest_sha256",
)


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _candidate_inputs(path: Path) -> dict[str, Any]:
    return CandidateReleaseInputs.model_validate_json(path.read_text(encoding="utf-8")).model_dump(
        mode="json"
    )


def _sha256(value: object, *, field: str) -> str:
    text = str(value)
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field} is not canonical SHA-256")
    return f"sha256:{text}"


def _one_of(payload: Mapping[str, Any], names: Iterable[str], *, source: str) -> Any:
    present = [(name, payload[name]) for name in names if payload.get(name) not in {None, ""}]
    if len(present) != 1:
        raise ValueError(f"{source} must contain exactly one of {list(names)}")
    return present[0][1]


def _safe_extract(archive: Path, destination: Path) -> list[str]:
    root = destination.resolve()
    names: list[str] = []
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"unsafe model archive path: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"model archive link is forbidden: {member.name}")
            normalized = member.name.casefold()
            if any(
                token in normalized for token in ("test.parquet", "heldout", "evaluation-report")
            ):
                raise ValueError(f"training archive contains a held-out artifact: {member.name}")
            names.append(member.name)
        handle.extractall(destination, filter="data")
    return names


def _single(root: Path, name: str, predicate: Any | None = None) -> Path:
    matches = [path for path in root.rglob(name) if predicate is None or predicate(path)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name}, found {len(matches)}")
    return matches[0]


def _source_field_checks(source: Mapping[str, Any], trial: Mapping[str, Any]) -> None:
    expected = {
        "candidate_run_id": trial["candidate_run_id"],
        "candidate_model_id": trial["candidate_model_id"],
        "candidate_artifact_s3_key": trial["candidate_artifact_s3_key"],
        "candidate_training_config_path": trial["candidate_training_config_path"],
        "candidate_training_config_s3_key": trial["candidate_training_config_s3_key"],
        "dataset_manifest_hash": trial["dataset_manifest_hash"],
        "training_run_kind": trial["training_run_kind"],
        "training_config_role": trial["training_config_role"],
        "git_sha": trial["training_git_sha"],
        "repository_dirty": False,
        "training_image_uri": trial["training_image_uri"],
        "training_image_digest": trial["training_image_digest"],
        "training_image_source_tag": trial["training_image_source_tag"],
        "training_hardware": trial["hardware_class"],
        "training_accelerator": trial["accelerator"],
        "training_region": trial["region"],
        "training_status": "succeeded",
        "source_identity_basis": trial["source_identity_basis"],
    }
    for field, value in expected.items():
        if source.get(field) != value:
            raise ValueError(f"candidate release inputs disagree on {field}")
    hash_fields = {
        "candidate_artifact_sha256": trial["candidate_artifact_sha256"],
        "candidate_checkpoint_sha256": trial["candidate_checkpoint_sha256"],
        "candidate_training_config_sha256": trial["candidate_training_config_sha256"],
        "candidate_training_config_file_sha256": trial["candidate_training_config_file_sha256"],
    }
    for field, value in hash_fields.items():
        if _sha256(source.get(field), field=field) != value:
            raise ValueError(f"candidate release inputs disagree on {field}")
    manifest_key = str(_one_of(source, RUN_MANIFEST_KEY_FIELDS, source="candidate inputs"))
    manifest_hash = _sha256(
        _one_of(source, RUN_MANIFEST_HASH_FIELDS, source="candidate inputs"),
        field="training_run_manifest_sha256",
    )
    if manifest_key != trial["training_run_manifest_s3_key"]:
        raise ValueError("candidate release inputs disagree on the run-manifest key")
    if manifest_hash != trial["training_run_manifest_sha256"]:
        raise ValueError("candidate release inputs disagree on the run-manifest hash")
    if "best_validation_ndcg_at_10" in source and not math.isclose(
        float(source["best_validation_ndcg_at_10"]),
        float(trial["best_validation_ndcg_at_10"]),
        rel_tol=0,
        abs_tol=1e-15,
    ):
        raise ValueError("candidate release inputs disagree on the validation metric")
    source_cost = float(source.get("training_billable_on_demand_upper_bound_usd", "nan"))
    if not math.isclose(
        source_cost,
        float(trial["training_billable_on_demand_upper_bound_usd"]),
        rel_tol=0,
        abs_tol=1e-15,
    ):
        raise ValueError("candidate release inputs disagree on the cost upper bound")


def _manifest_checks(
    manifest: RunManifest,
    *,
    trial: Mapping[str, Any],
    expected_git_sha: str,
) -> None:
    if manifest.run_type != "training" or manifest.status != "succeeded":
        raise ValueError("training RunManifest is not a successful training run")
    expected = {
        "run_id": trial["candidate_run_id"],
        "git_sha": expected_git_sha,
        "repository_dirty": False,
        "image_digest": trial["training_image_digest"],
        "config_hash": trial["candidate_training_config_sha256"],
        "dataset_manifest_hash": trial["dataset_manifest_hash"],
        "region": trial["region"],
        "job_id": trial["training_job_id"],
        "hardware": trial["hardware_class"],
        "accelerator": trial["accelerator"],
    }
    for field, value in expected.items():
        if getattr(manifest, field) != value:
            raise ValueError(f"training RunManifest disagrees on {field}")
    artifact_hash = str(trial["candidate_artifact_sha256"])
    artifact_key = str(trial["candidate_artifact_s3_key"])
    bound_names = [
        name
        for name, checksum in manifest.artifact_checksums.items()
        if checksum == artifact_hash
        and (
            manifest.artifact_uris[name] == artifact_key
            or manifest.artifact_uris[name].endswith("/" + artifact_key)
        )
    ]
    if len(bound_names) != 1:
        raise ValueError("training RunManifest does not uniquely bind the model archive")


def _trial(
    *,
    role: str,
    release_inputs_path: Path,
    release_inputs_s3_key: str,
    archive_path: Path,
    run_manifest_path: Path,
    run_manifest_s3_key: str,
    repository_root: Path,
    expected_git_sha: str,
) -> dict[str, Any]:
    source = _candidate_inputs(release_inputs_path)
    archive_hash = f"sha256:{sha256_file(archive_path)}"
    if (
        _sha256(source.get("candidate_artifact_sha256"), field="candidate_artifact_sha256")
        != archive_hash
    ):
        raise ValueError(f"{role} model archive differs from candidate release inputs")

    with tempfile.TemporaryDirectory(prefix=f"trial-selection-{role}-") as directory:
        extracted = Path(directory)
        _safe_extract(archive_path, extracted)
        summary_path = _single(
            extracted,
            "summary.json",
            lambda path: (
                (payload := _object(path)).get("command") == "train"
                and payload.get("status") == "succeeded"
            ),
        )
        summary = _object(summary_path)
        result = summary.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"{role} training summary has no result object")
        result = cast(dict[str, Any], result)
        config_path = _single(extracted, "frozen-experiment.yaml")
        config = load_frozen_experiment(config_path)
        checkpoint = _single(
            extracted,
            "best",
            lambda path: (
                path.is_dir()
                and f"sha256:{sha256_directory(path)}"
                == _sha256(result.get("checkpoint_checksum"), field="checkpoint_checksum")
            ),
        )
        del checkpoint

        committed_path_text = ROLE_PATHS[role]
        committed_path = repository_root / committed_path_text
        if not committed_path.is_file() or committed_path.read_bytes() != config_path.read_bytes():
            raise ValueError(f"{role} archive does not contain the exact committed configuration")
        if source.get("candidate_training_config_path") != committed_path_text:
            raise ValueError(f"{role} candidate inputs use the wrong committed config path")
        summary_git_sha = summary.get("git_sha")
        if summary_git_sha not in {"unavailable", expected_git_sha}:
            raise ValueError(f"{role} command summary claims a different source commit")
        if summary.get("repository_dirty") is not False:
            raise ValueError(f"{role} command summary claims a dirty source tree")

        required_result = {
            "candidate_run_id": source.get("candidate_run_id"),
            "candidate_model_id": result.get("candidate_model_id"),
            "candidate_artifact_s3_key": source.get("candidate_artifact_s3_key"),
            "candidate_artifact_sha256": archive_hash,
            "candidate_checkpoint_sha256": _sha256(
                result.get("checkpoint_checksum"), field="checkpoint_checksum"
            ),
            "candidate_release_inputs_s3_key": release_inputs_s3_key,
            "candidate_release_inputs_sha256": f"sha256:{sha256_file(release_inputs_path)}",
            "training_run_manifest_s3_key": run_manifest_s3_key,
            "training_run_manifest_sha256": f"sha256:{sha256_file(run_manifest_path)}",
            "training_summary_sha256": f"sha256:{sha256_file(summary_path)}",
            "frozen_config_file_sha256": f"sha256:{sha256_file(config_path)}",
            "candidate_training_config_path": committed_path_text,
            "candidate_training_config_s3_key": source.get("candidate_training_config_s3_key"),
            "candidate_training_config_file_sha256": f"sha256:{sha256_file(config_path)}",
            "candidate_training_config_sha256": config.config_hash,
            "config_id": config.config_id,
            "dataset_manifest_hash": config.dataset_manifest_hash,
            "input_template_version": config.input_template_version,
            "sampling_strategy": config.sampling_strategy,
            "hard_example_sources": config.hard_example_sources,
            "best_validation_ndcg_at_10": float(result["best_validation_ndcg_at_10"]),
            "training_git_sha": expected_git_sha,
            "repository_dirty": False,
            "training_run_kind": source.get("training_run_kind"),
            "training_config_role": source.get("training_config_role"),
            "training_image_uri": source.get("training_image_uri"),
            "training_image_source_tag": source.get("training_image_source_tag"),
            "training_billable_on_demand_upper_bound_usd": float(
                source.get("training_billable_on_demand_upper_bound_usd", "nan")
            ),
            "source_identity_basis": source.get("source_identity_basis"),
        }
        if required_result["candidate_run_id"] != source.get("candidate_run_id"):
            raise AssertionError("unreachable candidate run mismatch")
        source_expected = {
            "candidate_model_id": required_result["candidate_model_id"],
            "candidate_checkpoint_sha256": required_result["candidate_checkpoint_sha256"],
            "candidate_training_config_sha256": required_result["candidate_training_config_sha256"],
            "dataset_manifest_hash": required_result["dataset_manifest_hash"],
        }
        for field, value in source_expected.items():
            observed = source.get(field)
            if field.endswith("sha256"):
                observed = _sha256(observed, field=field)
            if observed != value:
                raise ValueError(f"{role} candidate inputs disagree on {field}")

        manifest = RunManifest.model_validate_json(run_manifest_path.read_text(encoding="utf-8"))
        required_result.update(
            {
                "training_image_digest": manifest.image_digest,
                "training_job_id": manifest.job_id,
                "region": manifest.region,
                "hardware_class": manifest.hardware,
                "accelerator": manifest.accelerator,
                "promotion_eligible": role == "candidate_treatment",
                "role": role,
            }
        )
        _source_field_checks(source, required_result)
        _manifest_checks(manifest, trial=required_result, expected_git_sha=expected_git_sha)
        return required_result


def _assert_single_factor_configs(trials: list[dict[str, Any]], repository_root: Path) -> None:
    by_role = {trial["role"]: trial for trial in trials}
    configs = {
        role: load_frozen_experiment(repository_root / ROLE_PATHS[role]).model_dump(mode="json")
        for role in ROLES
    }
    treatment = configs["candidate_treatment"]
    expected = {
        "random_negative_control": {
            "config_hash",
            "config_id",
            "hard_example_sources",
            "sampling_strategy",
        },
        "title_only_control": {"config_hash", "config_id", "input_template_version"},
    }
    for role, allowed in expected.items():
        observed = {key for key in treatment if treatment[key] != configs[role][key]}
        if observed != allowed:
            raise ValueError(
                f"{role} is not a single-factor control: expected {sorted(allowed)}, "
                f"observed {sorted(observed)}"
            )
    if {trial["config_id"] for trial in trials} != {
        configs[role]["config_id"] for role in ROLES
    } or set(by_role) != set(ROLES):
        raise ValueError("trial/config role inventory differs")


def build(args: argparse.Namespace) -> TrialSelection:
    repository_root = Path(args.repository_root).resolve()
    trials: list[dict[str, Any]] = []
    for role in ROLES:
        prefix = role.replace("_control", "").replace("candidate_", "")
        trials.append(
            _trial(
                role=role,
                release_inputs_path=Path(getattr(args, f"{prefix}_release_inputs")),
                release_inputs_s3_key=getattr(args, f"{prefix}_release_inputs_s3_key"),
                archive_path=Path(getattr(args, f"{prefix}_model_archive")),
                run_manifest_path=Path(getattr(args, f"{prefix}_run_manifest")),
                run_manifest_s3_key=getattr(args, f"{prefix}_run_manifest_s3_key"),
                repository_root=repository_root,
                expected_git_sha=args.git_sha,
            )
        )
    _assert_single_factor_configs(trials, repository_root)
    by_role = {trial["role"]: trial for trial in trials}
    treatment = by_role["candidate_treatment"]
    identity = sha256_value(
        {
            "git_sha": args.git_sha,
            "sources": [
                {
                    "role": trial["role"],
                    "release_inputs": trial["candidate_release_inputs_sha256"],
                    "run_manifest": trial["training_run_manifest_sha256"],
                    "model_archive": trial["candidate_artifact_sha256"],
                }
                for trial in trials
            ],
        }
    )
    contrasts = []
    for contrast_id, control_role, fields in (
        (
            "mixed_vs_random_sampling",
            "random_negative_control",
            ["config_hash", "config_id", "hard_example_sources", "sampling_strategy"],
        ),
        (
            "enriched_vs_title_input",
            "title_only_control",
            ["config_hash", "config_id", "input_template_version"],
        ),
    ):
        control = by_role[control_role]
        contrasts.append(
            {
                "contrast_id": contrast_id,
                "treatment_role": "candidate_treatment",
                "control_role": control_role,
                "controlled_difference_fields": fields,
                "treatment_validation_ndcg_at_10": treatment["best_validation_ndcg_at_10"],
                "control_validation_ndcg_at_10": control["best_validation_ndcg_at_10"],
                "treatment_minus_control": treatment["best_validation_ndcg_at_10"]
                - control["best_validation_ndcg_at_10"],
            }
        )
    artifact = TrialSelection.model_validate(
        {
            "schema_version": "1.0.0",
            "artifact_type": "validation_trial_selection",
            "selection_id": f"trial-selection-{identity[:20]}",
            "git_sha": args.git_sha,
            "repository_dirty": False,
            "dataset_manifest_hash": treatment["dataset_manifest_hash"],
            "split": "validation",
            "metric_name": "graded_ndcg@10",
            "test_access_count": 0,
            "heldout_accessed": False,
            "trial_count": 3,
            "selection_rule_id": "preregistered_treatment_controls_validation_only_v1",
            "selection_rule": SELECTION_RULE,
            "selected_role": "candidate_treatment",
            "selected_candidate_run_id": treatment["candidate_run_id"],
            "selected_candidate_model_id": treatment["candidate_model_id"],
            "selected_candidate_config_sha256": treatment["candidate_training_config_sha256"],
            "trials": trials,
            "contrasts": contrasts,
        }
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return artifact


def verify(args: argparse.Namespace) -> TrialSelection:
    selection_path = Path(args.selection)
    selection = TrialSelection.model_validate_json(selection_path.read_text(encoding="utf-8"))
    if selection.git_sha != args.git_sha:
        raise ValueError("trial selection belongs to a different Git commit")
    if args.dataset_manifest_hash and selection.dataset_manifest_hash != args.dataset_manifest_hash:
        raise ValueError("trial selection belongs to a different dataset")
    if args.candidate_run_id and selection.selected_candidate_run_id != args.candidate_run_id:
        raise ValueError("trial selection chose a different candidate run")
    if args.candidate_model_id and selection.selected_candidate_model_id != args.candidate_model_id:
        raise ValueError("trial selection chose a different candidate model")
    if args.candidate_config_sha256 and (
        selection.selected_candidate_config_sha256
        != _sha256(args.candidate_config_sha256, field="candidate_config_sha256")
    ):
        raise ValueError("trial selection chose a different candidate configuration")
    if args.candidate_artifact_s3_key or args.candidate_artifact_sha256:
        treatment = next(trial for trial in selection.trials if trial.role == "candidate_treatment")
        if treatment.candidate_artifact_s3_key != args.candidate_artifact_s3_key:
            raise ValueError("trial selection chose a different candidate model archive")
        if treatment.candidate_artifact_sha256 != _sha256(
            args.candidate_artifact_sha256, field="candidate_artifact_sha256"
        ):
            raise ValueError("trial selection chose a different candidate archive hash")

    repository_root = Path(args.repository_root).resolve()
    trial_dicts = [trial.model_dump(mode="json") for trial in selection.trials]
    _assert_single_factor_configs(trial_dicts, repository_root)
    if args.source_dir:
        source_dir = Path(args.source_dir)
        for trial in selection.trials:
            source_path = source_dir / f"{trial.role}.json"
            if f"sha256:{sha256_file(source_path)}" != trial.candidate_release_inputs_sha256:
                raise ValueError(f"{trial.role} candidate release inputs checksum changed")
            _source_field_checks(_candidate_inputs(source_path), trial.model_dump(mode="json"))
    if args.run_manifest_dir:
        manifest_dir = Path(args.run_manifest_dir)
        for trial in selection.trials:
            path = manifest_dir / f"{trial.role}.json"
            if f"sha256:{sha256_file(path)}" != trial.training_run_manifest_sha256:
                raise ValueError(f"{trial.role} RunManifest checksum changed")
            manifest = RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
            _manifest_checks(
                manifest,
                trial=trial.model_dump(mode="json"),
                expected_git_sha=args.git_sha,
            )
    return selection


def discover(args: argparse.Namespace) -> None:
    source = _candidate_inputs(Path(args.release_inputs))
    payload = {
        "candidate_artifact_s3_key": source.get("candidate_artifact_s3_key"),
        "training_run_manifest_s3_key": _one_of(
            source, RUN_MANIFEST_KEY_FIELDS, source="candidate inputs"
        ),
    }
    print(json.dumps(payload, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--repository-root", default=".")
    build_parser.add_argument("--git-sha", required=True)
    build_parser.add_argument("--output", required=True)
    for prefix in ("treatment", "random_negative", "title_only"):
        build_parser.add_argument(f"--{prefix.replace('_', '-')}-release-inputs", required=True)
        build_parser.add_argument(
            f"--{prefix.replace('_', '-')}-release-inputs-s3-key", required=True
        )
        build_parser.add_argument(f"--{prefix.replace('_', '-')}-model-archive", required=True)
        build_parser.add_argument(f"--{prefix.replace('_', '-')}-run-manifest", required=True)
        build_parser.add_argument(
            f"--{prefix.replace('_', '-')}-run-manifest-s3-key", required=True
        )
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--selection", required=True)
    verify_parser.add_argument("--repository-root", default=".")
    verify_parser.add_argument("--git-sha", required=True)
    verify_parser.add_argument("--dataset-manifest-hash")
    verify_parser.add_argument("--candidate-run-id")
    verify_parser.add_argument("--candidate-model-id")
    verify_parser.add_argument("--candidate-config-sha256")
    verify_parser.add_argument("--candidate-artifact-s3-key")
    verify_parser.add_argument("--candidate-artifact-sha256")
    verify_parser.add_argument("--source-dir")
    verify_parser.add_argument("--run-manifest-dir")
    discover_parser = subparsers.add_parser("discover")
    discover_parser.add_argument("--release-inputs", required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "build":
        artifact = build(args)
        print(json.dumps({"selection_id": artifact.selection_id}, sort_keys=True))
    elif args.command == "verify":
        artifact = verify(args)
        print(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "artifact_type": "trial_selection_verification",
                    "selection_id": artifact.selection_id,
                    "status": "verified",
                },
                sort_keys=True,
            )
        )
    else:
        discover(args)


if __name__ == "__main__":
    main()
