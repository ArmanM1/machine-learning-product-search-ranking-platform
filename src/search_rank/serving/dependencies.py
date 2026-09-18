"""Validated application settings and immutable process state."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from search_rank.artifacts.checksums import sha256_file
from search_rank.logging import log_event
from search_rank.schemas.api import (
    ModelSummary,
    PublicColdStartObservation,
    PublicEvaluationEvidence,
    PublicEvidenceEnvelope,
    PublicLatencyPercentiles,
    PublicOperationsEvidence,
    PublicOperationsPending,
    PublicOperationsVerified,
    PublicRunSummary,
    PublicValidationEvaluation,
    PublicValidationRunSummary,
    PublicWarmServingEvidence,
)
from search_rank.schemas.evidence import ReleaseManifest
from search_rank.schemas.workflow import DeploymentEvidence

from .model_loader import Ranker, load_rankers
from .query_store import QueryStore

LOGGER = logging.getLogger(__name__)
_MAX_OPERATIONAL_EVIDENCE_BYTES = 1_048_576
_ACCESS_DENIED_PENDING_SECONDS = 120


class OperationalEvidenceConflict(ValueError):
    """The canonical deployment record is malformed or bound to another release."""


class OperationalEvidenceUnavailable(RuntimeError):
    """The canonical deployment record could not be read from its private store."""


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEARCH_RANK_", extra="ignore", populate_by_name=True
    )

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
    artifact_bucket: str | None = Field(
        default=None,
        validation_alias="ARTIFACT_BUCKET",
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$",
    )
    public_prefix: Literal["public/"] = Field(default="public/", validation_alias="PUBLIC_PREFIX")
    lambda_function_version: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_FUNCTION_VERSION",
        pattern=r"^[1-9][0-9]*$",
    )


@dataclass
class ServiceState:
    settings: ServiceSettings
    query_store: QueryStore | None = None
    rankers: dict[str, Ranker] | None = None
    release_manifest: dict[str, Any] | None = None
    evidence: PublicEvidenceEnvelope | None = None
    s3_client: Any | None = None
    operational_access_denied_at: float | None = None
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

    def operational_evidence(self) -> PublicOperationsEvidence:
        """Read and sanitize the latest deployment record for the loaded release."""

        if not self.release_manifest:
            raise OperationalEvidenceConflict("release manifest is not loaded")
        manifest = ReleaseManifest.model_validate(self.release_manifest)
        pending = PublicOperationsPending(
            release_id=manifest.release_id,
            model_id=manifest.promoted_model_id,
        )
        if not self.settings.artifact_bucket:
            if self.settings.release_mode:
                raise OperationalEvidenceUnavailable("deployment evidence store is not configured")
            return pending
        if not self.settings.lambda_function_version:
            if self.settings.release_mode:
                raise OperationalEvidenceUnavailable("executing Lambda version is unavailable")
            return pending

        key = f"{self.settings.public_prefix}{manifest.release_id}/deployment-evidence.json"
        try:
            client = self.s3_client or boto3.client(
                "s3",
                config=Config(
                    connect_timeout=1,
                    read_timeout=2,
                    retries={"max_attempts": 2, "mode": "standard"},
                ),
            )
            response = client.get_object(
                Bucket=self.settings.artifact_bucket,
                Key=key,
                ChecksumMode="ENABLED",
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            # The runtime role intentionally has no ListBucket permission. S3
            # therefore reports a not-yet-created key as AccessDenied instead
            # of NoSuchKey. Pending is claim-safe: verified values still require
            # a readable, checksummed, fully validated canonical object.
            if code in {"NoSuchKey", "NotFound", "404"}:
                return pending
            if code in {"AccessDenied", "403"}:
                now = time.monotonic()
                if self.operational_access_denied_at is None:
                    self.operational_access_denied_at = now
                if now - self.operational_access_denied_at <= _ACCESS_DENIED_PENDING_SECONDS:
                    return pending
                raise OperationalEvidenceUnavailable(
                    "deployment evidence access remained denied after the publication window"
                ) from exc
            raise OperationalEvidenceUnavailable(
                "deployment evidence store is unavailable"
            ) from exc
        except Exception as exc:
            raise OperationalEvidenceUnavailable(
                "deployment evidence store is unavailable"
            ) from exc
        self.operational_access_denied_at = None

        content_length = response.get("ContentLength")
        content_type = response.get("ContentType")
        checksum = response.get("ChecksumSHA256")
        if (
            not isinstance(content_length, int)
            or content_length < 1
            or content_length > _MAX_OPERATIONAL_EVIDENCE_BYTES
            or content_type != "application/json"
            or not isinstance(checksum, str)
            or not checksum
        ):
            raise OperationalEvidenceConflict("deployment evidence object metadata is invalid")

        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise OperationalEvidenceConflict("deployment evidence object body is unavailable")
        try:
            try:
                payload = body.read(_MAX_OPERATIONAL_EVIDENCE_BYTES + 1)
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        except Exception as exc:
            raise OperationalEvidenceUnavailable("deployment evidence body is unavailable") from exc
        if not isinstance(payload, bytes):
            raise OperationalEvidenceConflict("deployment evidence object body is invalid")
        if len(payload) != content_length:
            raise OperationalEvidenceUnavailable("deployment evidence body was not read completely")
        if len(payload) > _MAX_OPERATIONAL_EVIDENCE_BYTES:
            raise OperationalEvidenceConflict("deployment evidence object length is invalid")
        expected_checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
        if checksum != expected_checksum:
            raise OperationalEvidenceConflict("deployment evidence object checksum is invalid")

        try:
            deployment = DeploymentEvidence.model_validate_json(payload)
        except ValidationError as exc:
            raise OperationalEvidenceConflict("deployment evidence contract is invalid") from exc
        if (
            deployment.release_id != manifest.release_id
            or deployment.model_id != manifest.promoted_model_id
        ):
            raise OperationalEvidenceConflict(
                "deployment evidence identity differs from the release"
            )
        if deployment.code_commit != self.settings.service_version:
            return pending
        if deployment.production_lambda_version != self.settings.lambda_function_version:
            return pending

        gate = deployment.candidate_api_gate
        cold = deployment.controlled_cold_start
        promoted_model = next(
            model for model in manifest.models if model.model_id == manifest.promoted_model_id
        )
        if cold.identifiers.dataset_manifest_hash != manifest.dataset_manifest_hash:
            raise OperationalEvidenceConflict(
                "controlled cold-start dataset differs from the release"
            )
        if cold.identifiers.model_artifact_checksum != promoted_model.artifact_checksum:
            raise OperationalEvidenceConflict(
                "controlled cold-start model differs from the release"
            )
        if cold.identifiers.region != gate.region:
            raise OperationalEvidenceConflict(
                "controlled cold-start region differs from the warm gate"
            )
        if cold.first_request.candidate_count != gate.candidate_count:
            raise OperationalEvidenceConflict(
                "controlled cold-start candidate count differs from the warm gate"
            )
        if cold.control_proof.reserved_concurrency != gate.reserved_concurrency:
            raise OperationalEvidenceConflict(
                "controlled cold-start reserved concurrency differs from the warm gate"
            )
        if cold.control_proof.provisioned_concurrency != gate.provisioned_concurrency:
            raise OperationalEvidenceConflict(
                "controlled cold-start provisioned concurrency differs from the warm gate"
            )
        if cold.lambda_report.configured_memory_mb != gate.lambda_memory_mb:
            raise OperationalEvidenceConflict(
                "controlled cold-start memory differs from the warm gate"
            )
        if deployment.production_api_smoke.candidate_count != gate.candidate_count:
            raise OperationalEvidenceConflict(
                "production smoke candidate count differs from the warm gate"
            )
        return PublicOperationsVerified(
            release_id=deployment.release_id,
            model_id=deployment.model_id,
            code_commit=deployment.code_commit,
            serving_image_digest=deployment.serving_image_digest,
            warm=PublicWarmServingEvidence(
                scope="deployed_api_gateway_lambda_gate",
                candidate_count=gate.candidate_count,
                warmup_request_count=gate.warmup_request_count,
                measured_request_count=gate.valid_request_count,
                successful_request_count=gate.valid_request_count - gate.failure_count,
                failure_count=gate.failure_count,
                concurrency=gate.concurrency,
                end_to_end_latency_ms=PublicLatencyPercentiles.model_validate(
                    gate.end_to_end_latency_ms.model_dump()
                ),
                model_latency_ms=PublicLatencyPercentiles.model_validate(
                    gate.model_latency_ms.model_dump()
                ),
                lambda_memory_mb=gate.lambda_memory_mb,
                architecture=gate.architecture,
                region=gate.region,
                reserved_concurrency=gate.reserved_concurrency,
                provisioned_concurrency=gate.provisioned_concurrency,
                controlled_cold_sample_included=gate.controlled_cold_sample_included,
            ),
            controlled_cold_start=PublicColdStartObservation(
                measurement_class=cold.measurement_class,
                sample_count=cold.sample_count,
                candidate_count=gate.candidate_count,
                end_to_end_latency_ms=cold.first_request.end_to_end_latency_ms,
                init_duration_ms=cold.lambda_report.init_duration_ms,
                model_load_duration_ms=cold.structured_startup.model_load_duration_ms,
                excluded_from_warm_latency=cold.excluded_from_warm_samples,
            ),
        )
