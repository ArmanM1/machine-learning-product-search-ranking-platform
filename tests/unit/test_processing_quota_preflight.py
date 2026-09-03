from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from search_rank.schemas.workflow import SageMakerProcessingQuotaPreflight

ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _valid_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "sagemaker_processing_quota_preflight",
        "checked_at": "2026-09-02T12:00:00Z",
        "region": "us-east-1",
        "service_code": "sagemaker",
        "instance_type": "ml.m5.xlarge",
        "quota_code": "L-0307F515",
        "quota_name": "ml.m5.xlarge for processing job usage",
        "applied_value": 1.0,
        "required_value": 1,
        "quota_guard_passed": True,
    }


def test_processing_quota_contract_accepts_only_the_exact_available_quota() -> None:
    evidence = SageMakerProcessingQuotaPreflight.model_validate(_valid_payload())
    assert evidence.applied_value == 1
    assert evidence.quota_guard_passed is True

    for field, value in (
        ("region", "us-west-2"),
        ("service_code", "ec2"),
        ("instance_type", "ml.m5.2xlarge"),
        ("quota_code", "L-4CEE6BA6"),
        ("quota_name", "ml.m5.xlarge for spot training job usage"),
        ("required_value", 2),
        ("quota_guard_passed", False),
    ):
        with pytest.raises(ValidationError):
            SageMakerProcessingQuotaPreflight.model_validate({**_valid_payload(), field: value})


@pytest.mark.parametrize("applied_value", [0, -1, float("inf"), float("nan")])
def test_processing_quota_contract_rejects_missing_or_nonfinite_capacity(
    applied_value: float,
) -> None:
    with pytest.raises(ValidationError):
        SageMakerProcessingQuotaPreflight.model_validate(
            {**_valid_payload(), "applied_value": applied_value}
        )


def test_release_checks_exact_processing_quota_before_heldout_access() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    credentials = workflow.index("aws-actions/configure-aws-credentials")
    quota_check = workflow.index("aws service-quotas get-service-quota")
    access_counter_function = workflow.index("reserve_counter()")
    create_processing_job = workflow.index("aws sagemaker create-processing-job")
    access_counter_call = workflow.index('reserve_counter "${first_counter}" 1')
    processing_job_call = workflow.index('submit_and_wait 1 "${first_counter}"')

    assert credentials < quota_check < access_counter_function < create_processing_job
    assert access_counter_call < processing_job_call
    assert '--region "${AWS_REGION}"' in workflow[quota_check : quota_check + 500]
    assert "--service-code sagemaker" in workflow[quota_check : quota_check + 500]
    assert "--quota-code L-0307F515" in workflow[quota_check : quota_check + 500]
    assert '"QuotaName": "ml.m5.xlarge for processing job usage"' in workflow
    assert "not math.isfinite(applied_value) or applied_value < 1" in workflow
    assert "SageMakerProcessingQuotaPreflight.model_validate(" in workflow
    assert 'Path("processing-quota-preflight.json").write_text(' in workflow


def test_release_publishes_only_validated_sanitized_quota_evidence_after_report() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    report_binding = workflow.index("report_id=\"$(jq -r '.report_id' evaluation-report.json)\"")
    evidence_validation = workflow.index("SageMakerProcessingQuotaPreflight.model_validate_json(")
    evidence_publication = workflow.index(
        "publish_public_json processing-quota-preflight.json \\\n"
        "            processing-quota-preflight.json processing-quota-preflight"
    )

    assert report_binding < evidence_validation < evidence_publication
    publication_helper = workflow.split("publish_public_json()", 1)[1].split(
        'public_readback="$(mktemp -d)"', 1
    )[0]
    assert 'local object_key="public/${report_id}/${relative_key}"' in publication_helper
    assert "--checksum-algorithm SHA256" in publication_helper
    assert '--tagging "RetentionClass=public"' in publication_helper
    assert "--if-none-match '*'" in publication_helper
    assert 'cmp -s "${source_file}" "${existing}"' in publication_helper
    upload_artifact = workflow.split("name: heldout-release-evidence-", 1)[1]
    assert "            processing-quota-preflight.json" in upload_artifact
    assert "processing-quota-response.private.json" not in upload_artifact
