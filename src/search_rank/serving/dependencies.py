"""Validated application settings and immutable process state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from search_rank.schemas.api import (
    ModelSummary,
    PublicEvaluationEvidence,
    PublicEvidenceEnvelope,
    PublicValidationEvaluation,
    PublicValidationRunSummary,
)

from .model_loader import Ranker, load_rankers
from .query_store import QueryStore


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

    @property
    def ready(self) -> bool:
        assets_ready = bool(self.query_store and self.rankers and self.release_manifest)
        return assets_ready and (not self.settings.release_mode or self.evidence is not None)

    def load(self) -> None:
        if not self.settings.release_manifest or not self.settings.curated_queries:
            return
        evidence: PublicEvidenceEnvelope | None = None
        if self.settings.public_evidence:
            payload = json.loads(self.settings.public_evidence.read_text(encoding="utf-8"))
            evidence = PublicEvidenceEnvelope.model_validate(payload)
        query_store = QueryStore.from_json(self.settings.curated_queries)
        rankers, release_manifest = load_rankers(self.settings.release_manifest)
        if evidence is not None:
            self._validate_evidence_binding(evidence, release_manifest)
        self.query_store = query_store
        self.rankers = rankers
        self.release_manifest = release_manifest
        self.evidence = evidence

    @staticmethod
    def _validate_evidence_binding(
        evidence: PublicEvidenceEnvelope, release_manifest: dict[str, Any]
    ) -> None:
        if evidence.run.dataset_manifest_hash != release_manifest["dataset_manifest_hash"]:
            raise ValueError("public evidence dataset hash differs from the release manifest")
        if evidence.run.git_sha != release_manifest["git_sha"]:
            raise ValueError("public evidence git SHA differs from the release manifest")
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
        if not isinstance(evaluation, PublicEvaluationEvidence):
            raise ValueError("verified evidence sections are inconsistent")
        if evaluation.report_id != release_manifest["evaluation_report_id"]:
            raise ValueError("public evidence report ID differs from the release manifest")
        if evaluation.candidate_model_id not in model_ids:
            raise ValueError("public evidence candidate is absent from the release manifest")
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
