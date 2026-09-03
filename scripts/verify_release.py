"""Verify an immutable release bundle without changing local or cloud state."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from search_rank.artifacts.checksums import sha256_directory, sha256_file
from search_rank.config import sha256_value
from search_rank.schemas.api import PublicEvidenceEnvelope
from search_rank.schemas.evaluation import EvaluationReport
from search_rank.schemas.evidence import BundleChecksums, EvaluationProvenance, ReleaseManifest
from search_rank.schemas.model import ModelArtifact
from search_rank.serving.dependencies import ServiceSettings, ServiceState
from search_rank.serving.query_store import QueryStore

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{7,64}$")


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"release path escapes bundle: {relative}")
    return path


def verify_release(release_dir: Path, *, load_models: bool) -> dict[str, Any]:
    root = release_dir.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"release directory does not exist: {root}")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("release bundles may not contain symbolic links")

    manifest_path = root / "release-manifest.json"
    query_path = root / "curated-queries.json"
    evidence_path = root / "public-evidence.json"
    bundle_path = root / "bundle-checksums.json"
    license_path = root / "LICENSE"
    notice_path = root / "NOTICE"
    for required in (
        manifest_path,
        query_path,
        evidence_path,
        bundle_path,
        license_path,
        notice_path,
    ):
        if not required.is_file():
            raise FileNotFoundError(f"release artifact is missing: {required.name}")

    manifest = ReleaseManifest.model_validate(_load_object(manifest_path)).model_dump(
        mode="json", exclude_none=True
    )
    required_fields = {
        "schema_version",
        "release_id",
        "promoted_model_id",
        "dataset_manifest_hash",
        "split_manifest_hash",
        "evaluation_report_id",
        "git_sha",
        "evidence_mode",
        "artifact_checksums",
        "models",
    }
    missing = required_fields - set(manifest)
    if missing:
        raise ValueError(f"release manifest is missing fields: {sorted(missing)}")
    if manifest["schema_version"] != "1.0.0":
        raise ValueError("unsupported release manifest schema version")
    if not SHA256.fullmatch(str(manifest["dataset_manifest_hash"])):
        raise ValueError("release dataset manifest hash is not canonical SHA-256")
    if not SHA256.fullmatch(str(manifest["split_manifest_hash"])):
        raise ValueError("release split manifest hash is not canonical SHA-256")
    if not GIT_SHA.fullmatch(str(manifest["git_sha"])):
        raise ValueError("release Git revision is not a canonical hexadecimal SHA")
    evidence_mode = str(manifest["evidence_mode"])
    if evidence_mode not in {"verified", "validation_only"}:
        raise ValueError("release manifest has an unsupported evidence mode")
    if evidence_mode == "verified" and not isinstance(manifest.get("provenance"), dict):
        raise ValueError("verified release manifest has no separated execution provenance")
    if evidence_mode == "validation_only" and "provenance" in manifest:
        raise ValueError("validation-only release cannot claim trained-candidate provenance")
    if not isinstance(manifest["models"], list) or len(manifest["models"]) < 2:
        raise ValueError("release must compare at least two public models")

    source_names = {
        name
        for name in ("evaluation-report.json", "baseline-summary.json")
        if (root / name).is_file()
    }
    expected_source = (
        "evaluation-report.json" if evidence_mode == "verified" else "baseline-summary.json"
    )
    if source_names != {expected_source}:
        raise ValueError("release must contain exactly the evidence source declared by its mode")
    expected_artifacts = {
        expected_source,
        "curated-queries.json",
        "public-evidence.json",
        "LICENSE",
        "NOTICE",
    }
    if evidence_mode == "verified":
        expected_artifacts.update({"candidate-model-artifact.json", "evaluation-provenance.json"})
    artifact_checksums = manifest["artifact_checksums"]
    if not isinstance(artifact_checksums, dict) or set(artifact_checksums) != expected_artifacts:
        raise ValueError("release artifact checksum inventory does not match its evidence mode")
    for name in sorted(expected_artifacts):
        path = _inside(root, name)
        if not path.is_file():
            raise FileNotFoundError(f"release evidence artifact is missing: {name}")
        expected = str(artifact_checksums[name])
        if not SHA256.fullmatch(expected):
            raise ValueError(f"release artifact has a non-canonical checksum: {name}")
        if expected != "sha256:" + sha256_file(path):
            raise ValueError(f"release artifact checksum mismatch: {name}")

    bundle = BundleChecksums.model_validate(_load_object(bundle_path))
    bundle_files = bundle.files
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != bundle_path
    }
    if set(bundle_files) != actual_files:
        raise ValueError("bundle checksum inventory does not exactly match release files")
    for relative, expected_value in sorted(bundle_files.items()):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError("bundle checksum inventory contains a non-canonical path")
        path = _inside(root, relative)
        if not path.is_file() or path == bundle_path:
            raise ValueError(f"bundle checksum path is not a regular release file: {relative}")
        expected = str(expected_value)
        if not SHA256.fullmatch(expected):
            raise ValueError(f"bundle file has a non-canonical checksum: {relative}")
        if expected != "sha256:" + sha256_file(path):
            raise ValueError(f"bundle file checksum mismatch: {relative}")

    model_ids: set[str] = set()
    verified_checkpoints: dict[str, str] = {}
    for model in manifest["models"]:
        if not isinstance(model, dict):
            raise ValueError("release model entries must be objects")
        model_id = str(model.get("model_id", ""))
        if not model_id or model_id in model_ids:
            raise ValueError("release model IDs must be unique and non-empty")
        model_ids.add(model_id)
        checksum = str(model.get("artifact_checksum", ""))
        if not SHA256.fullmatch(checksum):
            raise ValueError(f"model {model_id} has a non-canonical artifact checksum")
        kind = model.get("kind")
        if kind == "bm25":
            expected = f"sha256:{sha256_value({'model_id': model_id})}"
            if checksum != expected:
                raise ValueError("BM25 declaration checksum does not match its model ID")
            continue
        checkpoint_value = model.get("checkpoint")
        if not isinstance(checkpoint_value, str):
            raise ValueError(f"model {model_id} is missing its checkpoint path")
        checkpoint = _inside(root, checkpoint_value)
        if not checkpoint.is_dir():
            raise FileNotFoundError(f"model checkpoint is missing: {model_id}")
        actual = "sha256:" + sha256_directory(checkpoint)
        if actual != checksum:
            raise ValueError(f"model checkpoint checksum mismatch: {model_id}")
        verified_checkpoints[model_id] = actual

    if manifest["promoted_model_id"] not in model_ids:
        raise ValueError("promoted model is absent from the release model registry")
    QueryStore.from_json(query_path)
    evidence = PublicEvidenceEnvelope.model_validate_json(evidence_path.read_text(encoding="utf-8"))
    if evidence.evidence_mode != evidence_mode:
        raise ValueError("public evidence mode differs from the release manifest")
    ServiceState._validate_evidence_binding(evidence, manifest)
    report_path = root / "evaluation-report.json"
    if evidence_mode == "verified":
        report = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        if report.report_id != manifest["evaluation_report_id"]:
            raise ValueError("release manifest and evaluation report IDs differ")
        provenance = EvaluationProvenance.model_validate(
            _load_object(root / "evaluation-provenance.json")
        ).model_dump(mode="json")
        if (
            provenance.get("report_id") != report.report_id
            or provenance.get("split") != "test"
            or provenance.get("dataset_manifest_hash") != manifest["dataset_manifest_hash"]
            or provenance.get("split_manifest_hash") != manifest["split_manifest_hash"]
            or provenance.get("evaluation_git_sha") != manifest["git_sha"]
        ):
            raise ValueError("evaluation provenance differs from the verified release identity")
        artifact_path = root / "candidate-model-artifact.json"
        artifact = ModelArtifact.model_validate_json(artifact_path.read_text(encoding="utf-8"))
        training_provenance = manifest["provenance"]["training"]
        candidate_model = next(
            (
                model
                for model in manifest["models"]
                if model["model_id"] == artifact.model_id and model["kind"] == "fine_tuned"
            ),
            None,
        )
        if candidate_model is None:
            raise ValueError("candidate ModelArtifact has no matching fine-tuned release model")
        if (
            artifact.artifact_checksum != candidate_model["artifact_checksum"]
            or artifact.dataset_manifest_hash != manifest["dataset_manifest_hash"]
            or artifact.evaluation_report_id != report.report_id
            or artifact.evaluation_report_sha256 != "sha256:" + sha256_file(report_path)
            or artifact.selected_training_run_manifest_sha256
            != training_provenance["run_manifest_sha256"]
            or artifact.run_id != training_provenance["run_id"]
            or artifact.git_sha != training_provenance["git_sha"]
            or artifact.image_digest != training_provenance["image_digest"]
            or artifact.config_hash != training_provenance["config_hash"]
            or artifact.promoted != (manifest["promoted_model_id"] == artifact.model_id)
        ):
            raise ValueError(
                "candidate ModelArtifact differs from the selected training and evaluation evidence"
            )

    ready_verified = False
    if load_models:
        state = ServiceState(
            ServiceSettings(
                release_manifest=manifest_path,
                curated_queries=query_path,
                public_evidence=evidence_path,
                release_mode=True,
                web_dist=root / "web-dist-not-required-for-model-verification",
            )
        )
        state.load()
        if not state.ready:
            raise ValueError("service state remained not-ready after release load")
        ready_verified = True

    return {
        "schema_version": "1.0.0",
        "status": "passed",
        "release_id": manifest["release_id"],
        "promoted_model_id": manifest["promoted_model_id"],
        "model_count": len(model_ids),
        "checkpoint_count": len(verified_checkpoints),
        "evidence_mode": evidence_mode,
        "split_manifest_hash": manifest["split_manifest_hash"],
        "release_manifest_sha256": "sha256:" + sha256_file(manifest_path),
        "evidence_source_sha256": "sha256:" + sha256_file(root / expected_source),
        "curated_queries_sha256": "sha256:" + sha256_file(query_path),
        "public_evidence_sha256": "sha256:" + sha256_file(evidence_path),
        "license_sha256": "sha256:" + sha256_file(license_path),
        "notice_sha256": "sha256:" + sha256_file(notice_path),
        "bundle_checksums_sha256": "sha256:" + sha256_file(bundle_path),
        "metadata_verified": True,
        "model_load_and_readiness_verified": ready_verified,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_dir", type=Path)
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Verify hashes/contracts without loading model weights; not a readiness proof",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_release(args.release_dir, load_models=not args.metadata_only)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
