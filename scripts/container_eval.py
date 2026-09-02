"""SageMaker Processing entry point that exports the documented report path."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import yaml

from search_rank.artifacts.checksums import sha256_directory, sha256_file
from search_rank.data.io import load_dataset_manifest
from search_rank.training.configuration import load_frozen_experiment


def _discover_config(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"evaluation configuration does not exist: {path}")
        return path
    root = Path(os.environ.get("SM_CHANNEL_CONFIG", "/opt/ml/processing/input/config"))
    for name in ("release.yaml", "validation-v1.yaml", "release.yml"):
        candidate = root / name
        if candidate.is_file():
            return candidate.resolve()
    candidates = sorted([*root.rglob("*.yaml"), *root.rglob("*.yml")])
    if not candidates:
        raise FileNotFoundError(f"no evaluation configuration found below {root}")
    if len(candidates) != 1:
        raise ValueError("multiple evaluation configurations found; pass --config explicitly")
    return candidates[0].resolve()


def _verify_frozen_evaluation_config(path: Path, *, heldout: bool) -> str:
    actual = sha256_file(path)
    expected = os.environ.get("FROZEN_CONFIG_SHA256")
    if heldout and not expected:
        raise ValueError("held-out evaluation requires FROZEN_CONFIG_SHA256")
    if expected is not None and expected.removeprefix("sha256:") != actual:
        raise ValueError("frozen evaluation configuration checksum mismatch")
    return f"sha256:{actual}"


def _summary_from_stdout(stdout: str) -> Path:
    for line in reversed(stdout.splitlines()):
        try:
            value: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("summary"), str):
            return Path(value["summary"]).resolve()
    raise ValueError("evaluation command did not publish its summary path")


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with tarfile.open(archive, "r:*") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if target != destination_root and destination_root not in target.parents:
                raise ValueError(f"candidate archive contains an unsafe path: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"candidate archive contains a link: {member.name}")
        handle.extractall(destination, filter="data")


def _candidate_root(path: Path, staging: Path) -> Path:
    if path.is_file():
        if not tarfile.is_tarfile(path):
            raise ValueError("candidate input file must be a tar archive from SageMaker training")
        _safe_extract(path, staging)
        return staging
    if not path.is_dir():
        raise FileNotFoundError(f"candidate input does not exist: {path}")
    archives = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and tarfile.is_tarfile(candidate)
    )
    summaries = list(path.rglob("summary.json"))
    if archives and not summaries:
        if len(archives) != 1:
            raise ValueError("candidate input must contain exactly one SageMaker model archive")
        _safe_extract(archives[0], staging)
        return staging
    return path


def _training_summary(root: Path) -> tuple[dict[str, Any], Path]:
    matches: list[tuple[dict[str, Any], Path]] = []
    for path in sorted(root.rglob("summary.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("command") == "train":
            matches.append((payload, path))
    if len(matches) != 1:
        raise ValueError(
            "candidate artifact must contain exactly one successful training summary; "
            f"found {len(matches)}"
        )
    payload, path = matches[0]
    if payload.get("status") != "succeeded" or not isinstance(payload.get("result"), dict):
        raise ValueError("candidate training summary is not successful")
    return payload, path


def _checkpoint(root: Path, expected_checksum: str) -> Path:
    normalized = expected_checksum.removeprefix("sha256:")
    preferred = sorted(path for path in root.rglob("best") if path.is_dir())
    matches = [path for path in preferred if sha256_directory(path) == normalized]
    if len(matches) != 1:
        raise ValueError(
            "candidate artifact must contain exactly one checkpoint matching its training summary"
        )
    return matches[0].resolve()


def _find_manifest(root: Path) -> Path:
    for name in ("manifest.json", "current.json"):
        candidates = sorted(root.rglob(name))
        if len(candidates) == 1:
            return candidates[0].resolve()
        if len(candidates) > 1:
            raise ValueError(f"held-out input contains multiple {name} files")
    raise FileNotFoundError(f"held-out dataset manifest not found below {root}")


def _stage_baseline_summary(reference: Path, staging: Path) -> tuple[str, Path]:
    root = reference.parent if reference.is_file() else reference
    paths = [reference] if reference.is_file() else sorted(reference.rglob("*.json"))
    run_matches: list[tuple[dict[str, Any], Path]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("command") == "baseline-run"
            and payload.get("status") == "succeeded"
        ):
            run_matches.append((payload, path))
    if len(run_matches) != 1:
        raise ValueError(
            "baseline input must contain exactly one successful baseline-run command summary"
        )
    run_summary, _ = run_matches[0]
    artifact_hashes = run_summary.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        raise ValueError("baseline command summary has no artifact hashes")
    expected = str(artifact_hashes.get("baseline_summary", ""))
    if not expected.startswith("sha256:"):
        raise ValueError("baseline command summary has no baseline artifact checksum")
    candidates = [
        path for path in root.rglob("*.json") if "sha256:" + sha256_file(path) == expected
    ]
    if len(candidates) != 1:
        raise ValueError("baseline artifact matching the command summary was not found uniquely")
    artifact_path = candidates[0].resolve()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(artifact, dict) or artifact.get("split") != "validation":
        raise ValueError("baseline artifact must declare validation selection")
    selected = artifact.get("strongest_baseline_id")
    if not isinstance(selected, str) or not selected:
        raise ValueError("baseline artifact has no strongest baseline ID")
    result = run_summary.get("result")
    if not isinstance(result, dict):
        raise ValueError("baseline command summary has no result object")
    result["baseline_summary"] = str(artifact_path)
    artifact_paths = run_summary.get("artifact_paths")
    if isinstance(artifact_paths, dict):
        artifact_paths["baseline_summary"] = str(artifact_path)
    staged = staging / "baseline-command-summary.json"
    staged.write_text(json.dumps(run_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return selected, staged


def _stage_frozen_candidate_config(
    candidate_root: Path,
    explicit: Path | None,
    expected_config_hash: str,
    staging: Path,
) -> Path:
    candidates = (
        [explicit]
        if explicit
        else sorted([*candidate_root.rglob("*.yaml"), *candidate_root.rglob("*.yml")])
    )
    matches: list[Path] = []
    for path in candidates:
        if path is None or not path.is_file():
            continue
        try:
            config = load_frozen_experiment(path)
        except (OSError, ValueError):
            continue
        if config.config_hash == expected_config_hash:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError(
            "candidate input must provide exactly one frozen training config matching its hash"
        )
    destination = staging / "frozen-candidate.yaml"
    shutil.copy2(matches[0], destination)
    return destination


def _stage_cloud_inputs(
    config: Path,
    *,
    candidate_input: Path,
    candidate_config: Path | None,
    heldout_input: Path,
    dataset_manifest: Path | None,
    baseline_summary: Path | None,
    strongest_baseline_id: str | None,
    candidate_checkpoint_sha256: str,
    candidate_config_sha256: str,
    dataset_manifest_sha256: str,
    staging: Path,
) -> Path:
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("evaluation configuration must be a YAML mapping")
    candidate_root = _candidate_root(candidate_input, staging / "candidate")
    summary, _ = _training_summary(candidate_root)
    result = summary["result"]
    assert isinstance(result, dict)
    expected = str(result.get("checkpoint_checksum", ""))
    if not expected.startswith("sha256:"):
        raise ValueError("training summary has no candidate checkpoint checksum")
    declared_candidate = "sha256:" + candidate_checkpoint_sha256.removeprefix("sha256:")
    if expected != declared_candidate:
        raise ValueError("candidate checkpoint hash differs from the frozen workflow input")
    summary_config_hash = str(result.get("config_hash", ""))
    declared_config = "sha256:" + candidate_config_sha256.removeprefix("sha256:")
    if summary_config_hash != declared_config:
        raise ValueError("candidate training config hash differs from the frozen workflow input")
    checkpoint = _checkpoint(candidate_root, expected)
    frozen_config = _stage_frozen_candidate_config(
        candidate_root, candidate_config, declared_config, staging
    )
    result["checkpoint"] = str(checkpoint)
    result["frozen_config"] = str(frozen_config)
    summary["config_path"] = str(frozen_config)
    staged_summary = staging / "candidate-summary.json"
    staged_summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    raw["candidate_summary"] = str(staged_summary)
    selected_manifest = (
        dataset_manifest.resolve() if dataset_manifest else _find_manifest(heldout_input)
    )
    if not selected_manifest.is_file():
        raise FileNotFoundError(f"dataset manifest does not exist: {selected_manifest}")
    declared_manifest = "sha256:" + dataset_manifest_sha256.removeprefix("sha256:")
    dataset_contract, _ = load_dataset_manifest(selected_manifest)
    if dataset_contract.processed_checksum != declared_manifest:
        raise ValueError("processed dataset checksum differs from the frozen workflow input")
    raw["dataset_manifest"] = str(selected_manifest)
    selected = strongest_baseline_id or raw.get("strongest_baseline_id")
    if baseline_summary:
        baseline_selected, staged_baseline = _stage_baseline_summary(baseline_summary, staging)
        if selected and selected != baseline_selected:
            raise ValueError("baseline override differs from the validation baseline artifact")
        selected = baseline_selected
        raw["baseline_summary"] = str(staged_baseline)
    if str(raw.get("split", "")).casefold() == "test" and not baseline_summary:
        raise ValueError(
            "held-out evaluation requires the completed validation baseline evidence bundle"
        )
    if selected:
        raw["strongest_baseline_id"] = str(selected)
    staged_config = staging / "evaluation.yaml"
    staged_config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return staged_config


def _stage_access_counter(requested: int | None, previous: int | None) -> int | None:
    if requested is not None and previous is not None:
        raise ValueError("pass either expected or previous test-access count, not both")
    expected = (
        requested if requested is not None else (previous + 1 if previous is not None else None)
    )
    if expected is None:
        env_value = os.environ.get("TEST_ACCESS_COUNTER")
        expected = int(env_value) if env_value is not None else None
    if expected is None:
        return None
    count = expected
    if count < 1:
        raise ValueError("test-access counter must be a positive integer")
    path = Path("/app/artifacts/heldout-access.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"test_access_count": count - 1}) + "\n", encoding="utf-8")
    return count


def build_command(argv: list[str]) -> tuple[list[str], Path, tempfile.TemporaryDirectory[str]]:
    parser = argparse.ArgumentParser(
        description="Run validation or one explicitly authorized held-out evaluation."
    )
    parser.add_argument("--config", help="Evaluation configuration YAML")
    parser.add_argument("--heldout", action="store_true", help="Enable the guarded test split")
    parser.add_argument(
        "--candidate-bundle",
        "--candidate-input",
        dest="candidate_input",
        default=os.environ.get("SM_CHANNEL_CANDIDATE", "/opt/ml/processing/input/candidate"),
        help="Extracted SageMaker model artifact or its model.tar.gz",
    )
    parser.add_argument(
        "--heldout-input",
        default=os.environ.get("SM_CHANNEL_HELDOUT", "/opt/ml/processing/input/heldout"),
        help="Prepared held-out artifact directory",
    )
    parser.add_argument(
        "--candidate-config",
        default=os.environ.get("SM_CHANNEL_CANDIDATE_CONFIG"),
        help="Frozen candidate training YAML, if not included in the training model archive",
    )
    parser.add_argument("--dataset-manifest", help="Explicit prepared manifest or current pointer")
    parser.add_argument(
        "--candidate-checkpoint-sha256",
        default=os.environ.get("CANDIDATE_CHECKPOINT_SHA256"),
        help="Frozen SHA-256 of the uncompressed candidate checkpoint directory",
    )
    parser.add_argument(
        "--dataset-processed-sha256",
        "--dataset-manifest-sha256",
        dest="dataset_manifest_sha256",
        default=os.environ.get("DATASET_MANIFEST_HASH"),
        help="Frozen DatasetManifest.processed_checksum (bare hex or sha256: prefix)",
    )
    parser.add_argument(
        "--candidate-config-sha256",
        default=os.environ.get("CANDIDATE_CONFIG_SHA256"),
        help="Canonical hash recorded inside the frozen candidate training config",
    )
    parser.add_argument(
        "--baseline-summary",
        default=os.environ.get("SM_CHANNEL_BASELINE"),
        help="Validation baseline summary or directory used to recover the frozen winner",
    )
    parser.add_argument(
        "--strongest-baseline-id",
        default=os.environ.get("STRONGEST_BASELINE_ID"),
        help="Baseline selected on validation before held-out access",
    )
    counter = parser.add_mutually_exclusive_group()
    counter.add_argument("--test-access-counter", type=int, help="Expected counter for this run")
    counter.add_argument(
        "--previous-test-access-count", type=int, help="Counter value before this run"
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("SM_OUTPUT_DATA_DIR", "/opt/ml/processing/output"),
        help="SageMaker Processing output directory",
    )
    args = parser.parse_args(argv)
    if args.heldout and os.environ.get("ALLOW_HELDOUT_EVAL") != "1":
        raise ValueError("--heldout requires ALLOW_HELDOUT_EVAL=1")
    config = _discover_config(args.config)
    frozen_evaluation_checksum = _verify_frozen_evaluation_config(config, heldout=args.heldout)
    os.environ["SEARCH_RANK_FROZEN_EVALUATION_CONFIG_SHA256"] = frozen_evaluation_checksum
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = tempfile.TemporaryDirectory(prefix="search-rank-eval-")
    staged_config = config
    expected_counter: int | None = None
    if args.heldout:
        if (
            not args.candidate_checkpoint_sha256
            or not args.candidate_config_sha256
            or not args.dataset_manifest_sha256
        ):
            raise ValueError(
                "held-out evaluation requires candidate checkpoint, candidate config, and "
                "dataset manifest SHA-256 inputs"
            )
        staged_config = _stage_cloud_inputs(
            config,
            candidate_input=Path(args.candidate_input).expanduser().resolve(),
            candidate_config=(
                Path(args.candidate_config).expanduser().resolve()
                if args.candidate_config
                else None
            ),
            heldout_input=Path(args.heldout_input).expanduser().resolve(),
            dataset_manifest=(
                Path(args.dataset_manifest).expanduser().resolve()
                if args.dataset_manifest
                else None
            ),
            baseline_summary=(
                Path(args.baseline_summary).expanduser().resolve()
                if args.baseline_summary
                else None
            ),
            strongest_baseline_id=args.strongest_baseline_id,
            candidate_checkpoint_sha256=args.candidate_checkpoint_sha256,
            candidate_config_sha256=args.candidate_config_sha256,
            dataset_manifest_sha256=args.dataset_manifest_sha256,
            staging=Path(staging.name),
        )
        expected_counter = _stage_access_counter(
            args.test_access_counter, args.previous_test_access_count
        )
    os.environ["SEARCH_RANK_STAGED_EVALUATION_CONFIG_SHA256"] = (
        f"sha256:{sha256_file(staged_config)}"
    )
    command = [
        sys.executable,
        "-m",
        "search_rank.cli",
        "evaluate",
        "--config",
        str(staged_config),
    ]
    if args.heldout:
        command.append("--heldout")
    if expected_counter is not None:
        os.environ["SEARCH_RANK_EXPECTED_TEST_ACCESS_COUNTER"] = str(expected_counter)
    return command, output_dir, staging


def _export_outputs(summary_path: Path, output_dir: Path) -> None:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "succeeded":
        raise ValueError("evaluation summary did not report success")
    result = summary.get("result")
    if not isinstance(result, dict):
        raise ValueError("evaluation summary has no result object")
    report = Path(str(result["evaluation_report"])).resolve()
    curated = Path(str(result["curated_queries"])).resolve()
    provenance = Path(str(result["evaluation_provenance"])).resolve()
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    expected_counter = os.environ.get("SEARCH_RANK_EXPECTED_TEST_ACCESS_COUNTER")
    if expected_counter is not None and int(report_payload.get("test_access_count", -1)) != int(
        expected_counter
    ):
        raise ValueError("evaluation report test-access count differs from the authorized count")
    shutil.copy2(report, output_dir / "evaluation-report.json")
    shutil.copy2(curated, output_dir / "curated-queries.json")
    shutil.copy2(provenance, output_dir / "evaluation-provenance.json")
    shutil.copy2(summary_path, output_dir / "command-summary.json")


def main(argv: list[str] | None = None) -> int:
    try:
        command, output_dir, staging = build_command(sys.argv[1:] if argv is None else argv)
        with staging:
            completed = subprocess.run(
                command, cwd="/app", check=False, text=True, capture_output=True
            )
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        if completed.returncode:
            return completed.returncode
        _export_outputs(_summary_from_stdout(completed.stdout), output_dir)
        return 0
    except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"evaluation container preflight/export failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
