"""Validated application settings and immutable process state."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from search_rank.artifacts.checksums import sha256_file
from search_rank.logging import log_event
from search_rank.schemas.api import (
    ModelSummary,
    PublicEvaluationEvidence,
    PublicEvidenceEnvelope,
    PublicRunSummary,
    PublicValidationEvaluation,
    PublicValidationRunSummary,
)
from search_rank.schemas.evidence import ReleaseManifest

from .model_loader import Ranker, load_rankers
from .query_store import QueryStore

LOGGER = logging.getLogger(__name__)


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEARCH_RANK_", extra="ignore")

    service_version: str = "development"
    release_manifest: Path | None = None
    curated_queries: Path | None = None
    public_evidence: Path | None = None
    # Kept only so older local launch commands fail visibly through readiness
    # instead of silently treating a summary-only artifact as complete evidence.
    public_run_summary: Path | None = None
    release_mode: bool = False
    web_dist: Path = Path("web/dist")
    maximum_body_bytes: int = Field(default=16_384, ge=1024, le=1_048_576)


@dataclass
class ServiceState:
    settings: ServiceSettings
    query_store: QueryStore | None = None
    rankers: dict[str, Ranker] | None = None
    release_manifest: dict[str, Any] | None = None
    evidence: PublicEvidenceEnvelope | None = None
    model_load_duration_ms: float | None = None
    startup_succeeded: bool = False

    @property
    def ready(self) -> bool:
        assets_ready = bool(self.query_store and self.rankers and self.release_manifest)
        return assets_ready and (not self.settings.release_mode or self.evidence is not None)

    def load(self) -> None:
        if not self.settings.release_manifest or not self.settings.curated_queries:
            return
        started = time.perf_counter()
        try:
            raw_release_manifest = json.loads(
                self.settings.release_manifest.read_text(encoding="utf-8")
            )
            release_manifest = ReleaseManifest.model_validate(raw_release_manifest).model_dump(
                mode="json", exclude_none=True
            )
            self._verify_release_artifacts(release_manifest, self.settings.release_manifest)
            evidence: PublicEvidenceEnvelope | None = None
            if self.settings.public_evidence:
                payload = json.loads(self.settings.public_evidence.read_text(encoding="utf-8"))
                evidence = PublicEvidenceEnvelope.model_validate(payload)
            query_store = QueryStore.from_json(self.settings.curated_queries)
            rankers, loaded_manifest = load_rankers(self.settings.release_manifest)
            if loaded_manifest != release_manifest:
                raise ValueError("model loader and release validator read different manifests")
            if evidence is not None:
                self._validate_evidence_binding(evidence, release_manifest)
            self.query_store = query_store
            self.rankers = rankers
            self.release_manifest = release_manifest
            self.evidence = evidence
            self.model_load_duration_ms = (time.perf_counter() - started) * 1000.0
            self.startup_succeeded = True
            log_event(
                LOGGER,
                "service_startup_success",
                startup_success=True,
                model_load_duration_ms=self.model_load_duration_ms,
                model_id=release_manifest["promoted_model_id"],
                error_code=None,
            )
        except Exception:
            self.model_load_duration_ms = (time.perf_counter() - started) * 1000.0
            self.startup_succeeded = False
            LOGGER.exception(
                "service_startup_failed",
                extra={
                    "context": {
                        "startup_success": False,
                        "model_load_duration_ms": self.model_load_duration_ms,
                        "model_id": None,
                        "error_code": "MODEL_LOAD_FAILED",
                    }
                },
            )
            raise

    @staticmethod
    def _verify_release_artifacts(release_manifest: dict[str, Any], manifest_path: Path) -> None:
        """Verify every declared release file before readiness can become true."""

        root = manifest_path.parent.resolve()
        checksums = release_manifest.get("artifact_checksums")
        if not isinstance(checksums, dict) or not checksums:
            raise ValueError("release manifest has no artifact checksum inventory")
        for relative, expected in sorted(checksums.items()):
            declared = manifest_path.parent / str(relative)
            if declared.is_symlink():
                raise ValueError(f"release artifact may not be a symbolic link: {relative}")
            try:
                artifact = declared.resolve(strict=True)
                artifact.relative_to(root)
            except (FileNotFoundError, ValueError) as exc:
                raise ValueError(
                    f"release artifact is missing or escapes its bundle: {relative}"
                ) from exc
            if not artifact.is_file():
                raise ValueError(f"release artifact is not a regular file: {relative}")
            actual = f"sha256:{sha256_file(artifact)}"
            if actual != expected:
                raise ValueError(f"release artifact checksum mismatch: {relative}")

    @staticmethod
    def _validate_evidence_binding(
        evidence: PublicEvidenceEnvelope, release_manifest: dict[str, Any]
    ) -> None:
        release_manifest = ReleaseManifest.model_validate(release_manifest).model_dump(
            mode="json", exclude_none=True
        )
        if evidence.run.dataset_manifest_hash != release_manifest["dataset_manifest_hash"]:
            raise ValueError("public evidence dataset hash differs from the release manifest")
        if evidence.run.split_manifest_hash != release_manifest["split_manifest_hash"]:
            raise ValueError("public evidence split hash differs from the release manifest")
        if evidence.run.git_sha != release_manifest["git_sha"]:
            raise ValueError("public evidence git SHA differs from the release manifest")
        if evidence.evidence_mode == "verified":
            if not isinstance(evidence.run, PublicRunSummary):
                raise ValueError("verified evidence has no verified run provenance")
            manifest_provenance = release_manifest.get("provenance")
            if not isinstance(manifest_provenance, dict):
                raise ValueError("verified release manifest has no execution provenance")
            expected_provenance = {
                "training": evidence.run.training_provenance.model_dump(
                    mode="json", exclude_none=True
                ),
                "evaluation": evidence.run.evaluation_provenance.model_dump(
                    mode="json", exclude_none=True
                ),
            }
            if manifest_provenance != expected_provenance:
                raise ValueError("public execution provenance differs from the release manifest")
        models_by_id = {str(model["model_id"]): model for model in release_manifest["models"]}
        if len(models_by_id) != len(release_manifest["models"]):
            raise ValueError("release manifest contains duplicate model IDs")
        model_ids = set(models_by_id)
        promoted_model_id = str(release_manifest["promoted_model_id"])
        promoted_model = models_by_id.get(promoted_model_id)
        if promoted_model is None:
            raise ValueError("promoted model is absent from the release manifest")
        if evidence.run.model_artifact_checksum != promoted_model["artifact_checksum"]:
            raise ValueError("public evidence model checksum differs from the promoted model")
        if evidence.evidence_mode == "validation_only":
            if not isinstance(evidence.run, PublicValidationRunSummary) or not isinstance(
                evidence.evaluation, PublicValidationEvaluation
            ):
                raise ValueError("validation-only evidence sections are inconsistent")
            if evidence.evaluation.evidence_id != release_manifest["evaluation_report_id"]:
                raise ValueError("public evidence ID differs from the release manifest")
            if evidence.evaluation.selected_model_id not in model_ids:
                raise ValueError("validation-selected model is absent from the release manifest")
            if evidence.evaluation.selected_model_id != promoted_model_id:
                raise ValueError("validation selection differs from the release manifest")
            return
        evaluation = evidence.evaluation
        if not isinstance(evidence.run, PublicRunSummary):
            raise ValueError("verified evidence has no verified run provenance")
        if not isinstance(evaluation, PublicEvaluationEvidence):
            raise ValueError("verified evidence sections are inconsistent")
        if evaluation.report_id != release_manifest["evaluation_report_id"]:
            raise ValueError("public evidence report ID differs from the release manifest")
        if evaluation.candidate_model_id not in model_ids:
            raise ValueError("public evidence candidate is absent from the release manifest")
        candidate_model = models_by_id[evaluation.candidate_model_id]
        if (
            evidence.run.training_provenance.selected_model_artifact_checksum
            != candidate_model["artifact_checksum"]
        ):
            raise ValueError("training provenance differs from the candidate model artifact")
        if evaluation.strongest_baseline_model_id not in model_ids:
            raise ValueError("public evidence baseline is absent from the release manifest")
        expected_promoted = (
            evaluation.candidate_model_id
            if evaluation.release_status == "passed"
            else evaluation.strongest_baseline_model_id
        )
        if expected_promoted != promoted_model_id:
            raise ValueError("public evidence release decision differs from the release manifest")

    def model_summaries(self) -> list[ModelSummary]:
        if not self.release_manifest or (self.settings.release_mode and self.evidence is None):
            return []
        return [
            ModelSummary.model_validate(model["public_summary"])
            for model in self.release_manifest["models"]
        ]
