from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_deploy_model_id_gate_accepts_pinned_baseline_without_path_characters() -> None:
    workflow = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    pattern_line = next(line for line in workflow.splitlines() if '"${MODEL_ID}" =~' in line)
    pattern = pattern_line.split("=~", 1)[1].rsplit("]]", 1)[0].strip()

    accepted = (
        "candidate-candidate-v1-0123456789ab",
        "pretrained-cross-encoder@233902d25c440f23af6f7d6e94d2946bac0bee0a-enriched_v1",
    )
    rejected = (
        "../candidate",
        "candidate/model",
        "candidate model",
        "@candidate",
        "candidate@",
        "candidate@@revision",
        "candidate:latest",
    )
    assert all(3 <= len(value) <= 100 and re.fullmatch(pattern, value) for value in accepted)
    assert all(not re.fullmatch(pattern, value) for value in rejected)
    assert "((${#MODEL_ID} >= 3 && ${#MODEL_ID} <= 100))" in workflow


def test_training_workflow_binds_commit_tag_digest_and_run_manifest() -> None:
    workflow = (WORKFLOWS / "train.yml").read_text(encoding="utf-8")
    schema = json.loads(
        (ROOT / "schemas" / "json" / "run_manifest.schema.json").read_text(encoding="utf-8")
    )
    manifest_block = workflow.split("manifest = {", 1)[1].split("evidence = {", 1)[0]

    assert "TRAINING_IMAGE_SOURCE_TAG: sha-${{ github.sha }}" in workflow
    assert '--image-ids "imageTag=${TRAINING_IMAGE_SOURCE_TAG}"' in workflow
    assert ".imageDetails[0].imageDigest == $digest" in workflow
    assert 'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"' in workflow
    assert 'test -z "$(git status --porcelain --untracked-files=all)"' in workflow
    assert ".AlgorithmSpecification.TrainingImage == $image" in workflow
    assert ".ModelArtifacts.S3ModelArtifacts | startswith($output)" in workflow
    assert ".Environment.SEARCH_RANK_GIT_SHA == $commit" in workflow
    assert ".Environment.SEARCH_RANK_CLOUD_RUN_ID == $job" in workflow
    assert ".Environment.SEARCH_RANK_RUN_KIND == $run_kind" in workflow
    assert '.Environment.SEARCH_RANK_CHECKPOINT_DIR == "/opt/ml/checkpoints"' in workflow
    assert '.CheckpointConfig.LocalPath == "/opt/ml/checkpoints"' in workflow
    assert '"git_sha": source_git_sha' in manifest_block
    assert '"repository_dirty": False' in manifest_block
    assert '"actual_cost_usd": None' in manifest_block
    assert 'summary["git_sha"]' not in manifest_block
    assert all(f'"{field}":' in manifest_block for field in schema["required"])
    assert '"training_run_manifest_s3_key"' in workflow
    assert '"training_run_manifest_sha256"' in workflow
    assert 'model_manifest.get("run_id") == os.environ["CLOUD_TRAINING_RUN_ID"]' in workflow
    assert '"best_validation_ndcg_at_10"' in workflow
    assert '"training_run_kind"' in workflow
    assert '"training_config_role"' in workflow
    assert "training_config_role=candidate_treatment" in workflow
    assert "training_config_role=random_negative_control" in workflow
    assert "training_config_role=title_only_control" in workflow
    assert "--if-none-match '*'" in workflow
    assert 'quota_code="L-4CEE6BA6"' in workflow
    assert 'quota_code="L-944F78BB"' in workflow
    assert "aws service-quotas get-service-quota" in workflow
    assert "and value >= 1" in workflow
    assert '"managed_spot_quota_preflight"' in workflow
    assert "validate_training_contracts.py config" in workflow
    assert '--instance-type "${INSTANCE_TYPE}"' in workflow
    assert '"accelerator": actual_accelerator' in workflow
    assert '"device_type": actual_device_type' in workflow
    assert '"cuda_available": cuda_available' in workflow
    assert '"cuda_device_count": cuda_device_count' in workflow
    assert "validate_training_contracts.py evidence" in workflow


def test_training_oidc_role_can_describe_only_the_training_repository() -> None:
    iam = (ROOT / "infra" / "terraform" / "modules" / "platform" / "iam.tf").read_text(
        encoding="utf-8"
    )
    statement = iam.split('sid       = "VerifyExactTrainingImageDigest"', 1)[1].split(
        "statement {", 1
    )[0]
    assert 'actions   = ["ecr:DescribeImages"]' in statement
    assert 'resources = [aws_ecr_repository.images["train"].arn]' in statement
    quota_statement = iam.split('sid       = "ReadManagedSpotTrainingQuota"', 1)[1].split(
        "statement {", 1
    )[0]
    assert 'actions   = ["servicequotas:GetServiceQuota"]' in quota_statement
    assert 'resources = ["*"]' in quota_statement


def test_training_inline_python_is_syntactically_valid() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "train.yml").read_text(encoding="utf-8"))
    scripts = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    snippets = [
        snippet.split("\nPY", 1)[0]
        for script in scripts
        for snippet in script.split("python - <<'PY'\n")[1:]
    ]
    assert len(snippets) >= 3
    for index, snippet in enumerate(snippets):
        compile(snippet, f"train-inline-{index}.py", "exec")


def test_failed_heldout_gate_publishes_evidence_without_promoting_candidate() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    benchmark = (WORKFLOWS / "benchmark-serving.yml").read_text(encoding="utf-8")

    assert "if: steps.release_gate.outputs.decision == 'promote_candidate'" not in release
    assert 'prefix="promoted/releases/${REPORT_ID}/"' in release
    assert 'test "${active_model_id}" = "$(jq -r \'.model_id\' previous-pointer.json)"' in release
    assert "release_decision: $decision" in release
    assert "gate_passed: $gate_passed" in release
    assert "evaluated_candidate_model_id: $candidate" in release
    assert "PromotionPointer.model_validate_json" in release
    assert '.bundle_s3_key == ("promoted/releases/" + $release + "/")' in deploy
    assert '.evaluation.release_status == "failed"' in deploy
    assert ".evaluation.strongest_baseline_model_id == $manifest.promoted_model_id" in deploy
    assert 'model_tag="model-${model_slug}-${model_identity_hash}-${model_hash}"' in deploy
    assert "bundle_s3_key=\"$(jq -er '.bundle_s3_key' current-pointer.json)\"" in benchmark
    assert 'status == "failed"' in benchmark
    assert 'evaluation.get("strongest_baseline_model_id") == MODEL_ID' in benchmark
    assert 'evaluation.get("candidate_model_id") != MODEL_ID' in benchmark
    assert 'pointer.get("release_decision") == "retain_baseline"' in benchmark


def test_release_keeps_selected_training_and_processing_provenance_separate() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    assert '--trial-selection "$(pwd)/trial-selection.json"' in release
    assert "--selected-training-run-manifest" in release
    assert "--selected-training-model-artifact" in release
    assert 'test -f "${bundle}/candidate-model-artifact.json"' in release
    assert "validate_release_artifacts.py bundle" in release
    assert "processing_job_wall_clock_sum" in (ROOT / "src/search_rank/schemas/api.py").read_text(
        encoding="utf-8"
    )
    assert "training.trial_selection_sha256" in release
    assert "training.run_manifest_sha256" in release
    assert 'release.get("provenance")' in release
    assert "with_entries(select(.value != null))) == $manifest.provenance.training" in deploy
    assert "with_entries(select(.value != null))) == $manifest.provenance.evaluation" in deploy
    assert ".run.evaluation_provenance.clean_execution_count == 2" in deploy
    assert "test -f .release/model/candidate-model-artifact.json" in deploy
    assert "scripts/verify_release.py" in deploy
    assert "ModelArtifact.model_validate_json" in deploy
    assert 'release.artifact_checksums["candidate-model-artifact.json"]' in deploy
    assert "artifact.selected_training_run_manifest_sha256" in deploy
    assert "artifact.promoted" in deploy
    assert "publish_public_json trial-selection.json" not in release
    artifact_paths = release.split("name: heldout-release-evidence-", 1)[1]
    assert "            trial-selection.json" not in artifact_paths
    assert "            trial-selection-binding.json" in artifact_paths
    assert "            trial-selection-verification.json" in artifact_paths


def test_split_manifest_identity_is_derived_and_bound_across_release_surfaces() -> None:
    prepare = (WORKFLOWS / "prepare-data.yml").read_text(encoding="utf-8")
    bootstrap = (WORKFLOWS / "bootstrap-baseline.yml").read_text(encoding="utf-8")
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    benchmark = (WORKFLOWS / "benchmark-serving.yml").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "validate_benchmark_contracts.py").read_text(encoding="utf-8")

    assert '"split_manifest_hash": split_manifest_hash' in prepare
    assert '.split_manifest_hash | select(test("^sha256:[0-9a-f]{64}$"))' in bootstrap
    assert '.split_manifest_hash | select(test("^sha256:[0-9a-f]{64}$"))' in release
    assert ".result.split_manifest_hash == $split" in release
    assert ".split_manifest_hash == $split" in release
    assert ".run.split_manifest_hash == $manifest.split_manifest_hash" in deploy
    assert 'manifest.get("split_manifest_hash"), "release split manifest identity"' in benchmark
    assert 'run.get("split_manifest_hash") != split_hash' in benchmark
    assert "release.split_manifest_hash == public_run.split_manifest_hash" in validator


def test_release_binds_baseline_evidence_to_current_clean_commit_and_config() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "validate_release_artifacts.py").read_text(encoding="utf-8")

    assert 'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"' in release
    assert 'test -z "$(git status --porcelain --untracked-files=all)"' in release
    assert 'test "${BASELINE_CONFIG_PATH}" = "configs/experiments/baselines-v1.yaml"' in release
    assert '--baseline-config-file-sha256 "${BASELINE_CONFIG_FILE_SHA256}"' in release
    assert '--expected-git-sha "${GITHUB_SHA}"' in release
    assert "baseline-evidence" in release
    assert "CommandSummary.model_validate_json" in validator
    assert "BaselineSummary.model_validate_json" in validator
    assert "command.git_sha != expected_git_sha" in validator
    assert "command.repository_dirty" in validator
    assert "baseline.config_hash != semantic_config_hash" in validator
    assert "VALIDATION_BASELINE_CONFIG_HASH: $baseline_config_hash" in release
    assert ".git_sha == $git and .repository_dirty == false" in release
    assert ".validation_baseline_summary_checksum == $baseline_summary" in release


def test_release_deploy_and_benchmark_inline_python_is_syntactically_valid() -> None:
    for workflow_name in ("release.yml", "deploy.yml", "benchmark-serving.yml"):
        workflow = yaml.safe_load((WORKFLOWS / workflow_name).read_text(encoding="utf-8"))
        scripts = [
            step["run"]
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if isinstance(step, dict) and isinstance(step.get("run"), str)
        ]
        snippets = [
            match.group(1)
            for script in scripts
            for match in re.finditer(r"<<'PY'\n(.*?)\nPY(?:\n|$)", script, re.DOTALL)
        ]
        assert snippets, workflow_name
        for index, snippet in enumerate(snippets):
            compile(snippet, f"{workflow_name}-inline-{index}.py", "exec")


def test_benchmark_validates_then_immutably_publishes_and_revalidates_readback() -> None:
    workflow = (WORKFLOWS / "benchmark-serving.yml").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "validate_benchmark_contracts.py").read_text(encoding="utf-8")
    validation_step = workflow.index("Validate and checksum the complete evidence bundle")
    publication_step = workflow.index("Publish the immutable validated performance evidence")

    assert validation_step < publication_step
    assert workflow.count("scripts/validate_benchmark_contracts.py") == 2
    assert '"controlled-cold-start.json"' in workflow
    assert "BenchmarkCostPreflight" in validator
    assert "BenchmarkLambdaConfiguration" in validator
    assert "ColdStartEvidence" in validator
    assert "PerformanceReport" in validator
    assert "PerformanceValidation" in validator
    assert "BundleChecksums" in validator
    assert "PromotionPointer" in validator
    assert "ReleaseManifest" in validator
    assert "PublicEvidenceEnvelope" in validator
    assert "DeploymentEvidence" in validator
    assert "put_immutable_or_verify_identical()" in workflow
    assert "--if-none-match '*'" in workflow[publication_step:]
    assert 'cmp -s "${source_file}" "${existing_file}"' in workflow
    assert 'cmp -s "${file}" "${readback_dir}/${relative}"' in workflow
    assert "--checksum-mode ENABLED" in workflow
    assert "--published-objects published-benchmark-objects.json" in workflow
    assert (
        'prefix="public/${RELEASE_ID}/performance/runs/${BENCHMARK_RUN_ID}/'
        'sha256-${bundle_digest}/"' in workflow
    )
    assert 'prefix="public/${RELEASE_ID}/performance/github-' not in workflow


def _serving_model_tag(model_id: str, release_manifest_sha256: str) -> str:
    slug = model_id.replace("@", "-at-")[:80]
    identity = hashlib.sha256(model_id.encode()).hexdigest()[:12]
    return f"model-{slug}-{identity}-{release_manifest_sha256[:12]}"


def test_deploy_derives_bounded_docker_safe_tags_for_baseline_and_negative_release() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    pinned_baseline = (
        "pretrained-cross-encoder@233902d25c440f23af6f7d6e94d2946bac0bee0a-enriched_v1"
    )
    initial_tag = _serving_model_tag(pinned_baseline, "1" * 64)
    retained_baseline_tag = _serving_model_tag(pinned_baseline, "2" * 64)

    for tag in (initial_tag, retained_baseline_tag):
        assert 1 <= len(tag) <= 128
        assert re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag)
        assert "@" not in tag
    assert initial_tag != retained_baseline_tag
    assert 'model_slug="${MODEL_ID//@/-at-}"' in deploy
    assert 'model_slug="${model_slug:0:80}"' in deploy
    assert 'model_identity_hash="$(printf \'%s\' "${MODEL_ID}" | sha256sum | cut -c1-12)"' in deploy
    assert 'model_tag="model-${model_slug}-${model_identity_hash}-${model_hash}"' in deploy
    assert "((${#tag} >= 1 && ${#tag} <= 128))" in deploy
    assert '[[ "${tag}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]' in deploy


def test_deploy_reuses_only_content_identical_immutable_ecr_images() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    assert "lookup_tag_digest()" in deploy
    assert "verify_registry_image_content()" in deploy
    assert "ensure_immutable_tag()" in deploy
    assert "Immutable ECR tags disagree on image digest; refusing reuse." in deploy
    assert "existing ECR image does not embed the exact release bundle" in deploy
    assert "io.product-search.release-manifest-sha256=sha256:${release_manifest_sha256}" in deploy
    assert "aws ecr batch-get-image" in deploy
    assert "aws ecr put-image" in deploy
    assert 'test "$(lookup_tag_digest "${tag}")" = "${digest}"' in deploy
    assert deploy.count('docker push "${SERVE_REPOSITORY}:${release_tag}"') == 1
    assert 'docker push "${SERVE_REPOSITORY}:${sha_tag}"' not in deploy
    assert 'docker push "${SERVE_REPOSITORY}:${model_tag}"' not in deploy


def test_deploy_browser_checks_use_real_mode_status_and_candidate_canary() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    assert "Verified evidence" not in deploy
    assert deploy.count("verified: 'Verified release'") >= 2
    assert deploy.count("validation_only: 'Validation-only evidence'") >= 2
    assert "printf 'RELEASE_EVIDENCE_MODE=%s\\n'" in deploy
    assert "await page.getByText(expectedStatus, { exact: true }).waitFor()" in deploy
    assert "restore_canary_alias()" in deploy
    assert "trap 'restore_canary_alias \"$?\"' EXIT" in deploy
    assert "page.route(`${origin.origin}/**`" in deploy
    assert "staged-canary-service-disabled.txt" in deploy
    assert '"${current_revision}" == "${expected_canary_revision}"' in deploy
    assert '"${current_revision}" == "${previous_revision}"' in deploy
    assert "staged-canary-restored-revision.txt" in deploy
    assert '--revision-id "${previous_revision}"' in deploy
    assert '--name production \\\n            --function-version "${candidate_version}"' in deploy
    assert '"$(cat ../cloudfront-url.txt)/healthz" > ../staged-candidate-health.json' in deploy
    assert '.status == "ok" and .service_version == $version' in deploy


def test_deploy_advances_staged_decision_only_after_production_verification() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    decision_publication = release.split(
        "name: Publish the exact decision bundle and stage the deployment pointer", 1
    )[-1].split("name: heldout-release-evidence-", 1)[0]
    assert 'decision_key="promoted/decisions/${REPORT_ID}.json"' in decision_publication
    assert (
        "put_promoted_immutable_or_verify_identical \\\n"
        '            promotion-pointer.json "${decision_key}" application/json'
        in decision_publication
    )
    decision_call = (
        "put_promoted_immutable_or_verify_identical \\\n"
        '            promotion-pointer.json "${decision_key}" application/json'
    )
    assert decision_publication.index('decision_key="promoted/decisions/${REPORT_ID}.json"') < (
        decision_publication.index(decision_call)
    )
    assert decision_publication.index("PromotionPointer.model_validate_json") < (
        decision_publication.index('decision_key="promoted/decisions/${REPORT_ID}.json"')
    )
    assert "--if-none-match '*'" in decision_publication
    assert 'cmp -s "${source_file}" "${existing}"' in decision_publication
    assert "--key promoted/current.json" not in decision_publication
    assert 'decision_pointer_key="promoted/decisions/${RELEASE_ID}.json"' in deploy
    assert "if: steps.production_verification.outcome == 'success'" in deploy
    assert deploy.index("Verify the activated API and complete browser flow") < deploy.index(
        "Advance the live pointer only after production verification passes"
    )
    advance = deploy.split(
        "name: Advance the live pointer only after production verification passes", 1
    )[1].split("name: Publish deployment evidence", 1)[0]
    assert "PromotionPointer.model_validate_json" in advance
    assert '--if-match "$(cat previous-promotion-pointer-etag.txt)"' in advance
    assert "cmp --silent promotion-pointer.json active-promotion-pointer.json" in advance
    assert "Compensate any failure or cancellation after a production mutation" in deploy
    assert "Live promotion pointer is neither the prior nor candidate pointer" in deploy
    assert "touch rollback-complete.txt" in deploy


def test_deploy_validates_and_cas_versions_durable_evidence() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    static = deploy.split("publish_static_file_immutable()", 1)[1].split(
        "Browser-smoke the staged static candidate", 1
    )[0]
    evidence = deploy.split("Publish deployment evidence only after", 1)[1].split(
        "Compensate any failure after", 1
    )[0]

    assert "--if-none-match '*'" in static
    assert 'cmp --silent "${source_file}" existing-static-object.bin' in static
    assert "immutable static release inventory differs from the local build" in static
    assert "DeploymentEvidence.model_validate_json" in evidence
    assert evidence.index("DeploymentEvidence.model_validate_json") < evidence.index(
        "aws s3api put-object"
    )
    assert "--if-none-match '*'" in evidence
    assert '--if-match "$(cat prior-deployment-evidence-etag.txt)"' in evidence
    assert "S3 versioning preserves every prior successful deployment record" in evidence
    assert "existing-deployment-evidence.json" not in evidence
    assert "deployment-production-alias.json" in evidence
    assert "deployment-production-function.json" in evidence
    assert ".Code.ResolvedImageUri == $image" in evidence
    assert "activated-lambda-alias-revision.txt" in evidence
    assert "AutomaticDeploymentRollback.model_validate_json" in deploy
    assert "ManualRollbackEvidence.model_validate_json" in deploy
    assert (
        'rollback_evidence_key="public/${RELEASE_ID}/rollback-evidence-${GITHUB_RUN_ID}-attempt-${GITHUB_RUN_ATTEMPT}.json"'
        in deploy
    )
    assert "cmp --silent rollback-evidence.json existing-rollback-evidence.json" in deploy


def test_serving_git_sha_is_bound_through_terraform_and_health_smoke() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    serving = (ROOT / "infra/terraform/modules/platform/serving.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/terraform/modules/platform/variables.tf").read_text(encoding="utf-8")

    assert '-var="serving_git_sha=${GITHUB_SHA}"' in deploy
    assert "SEARCH_RANK_SERVICE_VERSION  = var.serving_git_sha" in serving
    assert 'regex("^[0-9a-f]{40}$", var.serving_git_sha)' in variables
    assert "candidate-health.json" in deploy
    assert "staged-candidate-health.json" in deploy
    assert "production-health.json" in deploy
    assert deploy.count('.status == "ok" and .service_version == $version') >= 3


def test_deploy_retry_forces_a_fresh_identity_bound_lambda_version() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    serving = (ROOT / "infra/terraform/modules/platform/serving.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/terraform/modules/platform/variables.tf").read_text(encoding="utf-8")

    nonce = "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${RELEASE_ID}"
    assert f'-var="serving_deployment_nonce={nonce}"' in deploy
    assert "SEARCH_RANK_DEPLOYMENT_NONCE = var.serving_deployment_nonce" in serving
    assert "<run-id>-<attempt>-<release-id>" in variables
    assert f'--arg nonce "{nonce}"' in deploy
    assert ".Configuration.Environment.Variables.SEARCH_RANK_DEPLOYMENT_NONCE == $nonce" in deploy
    assert ".Code.ResolvedImageUri == $image" in deploy
    assert 'test "${candidate_version}" != "${previous_candidate_version}"' in deploy
    assert "prior-deployment-evidence-etag.txt" in deploy
    assert 'deployment_evidence_key="public/${RELEASE_ID}/deployment-evidence.json"' in deploy


def test_manual_rollback_is_prebound_smoked_then_cas_advanced_and_compensated() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    rollback = deploy.split("name: Restore model pointer, Lambda alias, and static release", 1)[1]

    validation = rollback.index("DeploymentEvidence.model_validate_json")
    first_mutation = rollback.index("transition_started=1")
    smoke = rollback.index("scripts/smoke_test.py")
    pointer_put = rollback.index("--body rollback-current.json")
    evidence_publish = rollback.index("rollback_evidence_key=")
    trap_disabled = rollback.index("trap - EXIT INT TERM", evidence_publish)
    assert validation < first_mutation < smoke < pointer_put < evidence_publish < trap_disabled

    assert "deployment.promoted_pointer_version_id == expected_pointer_version" in rollback
    assert "deployment.production_lambda_version == expected_version" in rollback
    assert "release.release_id == target.release_id" in rollback
    assert "release.promoted_model_id == target.model_id" in rollback
    assert "release.evidence_mode == target.evidence_mode" in rollback
    assert 'environment.get("SEARCH_RANK_SERVICE_VERSION") == deployment.code_commit' in rollback
    assert "release.git_sha == target.git_sha" in rollback
    assert "deployment.code_commit == target.git_sha" not in rollback
    assert "resolved_image == expected_image" in rollback
    assert 'os.environ["SERVE_REPOSITORY"] + "@" + deployment.serving_image_digest' in rollback
    assert '--if-match "${previous_pointer_etag}"' in rollback
    assert '--revision-id "${current_alias_revision}"' in rollback
    assert "restore_previous_state()" in rollback
    assert "trap 'restore_previous_state \"$?\"' EXIT" in rollback
    assert "trap 'exit 130' INT" in rollback
    assert "trap 'exit 143' TERM" in rollback
    rollback_compensation = rollback.split("restore_previous_state()", 1)[1].split(
        "trap 'restore_previous_state", 1
    )[0]
    assert 'exit "${original_status}"' in rollback_compensation
    assert "exit 1" not in rollback_compensation
    assert "--body pre-manual-rollback-pointer.json" in rollback
    assert "Live promotion pointer changed concurrently" in rollback
    assert "rollback-target-static" in rollback
    assert "rollback static verification failed" in rollback
    assert '[("<root>", index_path)]' in rollback
    assert "rollback-browser-desktop.png" in rollback
    assert "rollback-browser-mobile.png" in rollback
    assert "ROLLBACK_HAS_FINE_TUNED_CANDIDATE" in rollback
    assert "await compare.waitFor()" in rollback
    assert "await labels.uncheck()" in rollback
    assert "await page.getByRole('link', { name: 'Failures', exact: true }).click()" in rollback


def test_deploy_static_and_compensation_paths_are_fail_closed() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    iam = (ROOT / "infra/terraform/modules/platform/iam.tf").read_text(encoding="utf-8")
    staged = deploy.split("name: Build and stage the immutable static release", 1)[1].split(
        "name: Browser-smoke the staged static candidate", 1
    )[0]
    activation = deploy.split(
        "name: Capture rollback state and activate the smoke-tested candidate", 1
    )[1].split("name: Verify the activated API", 1)[0]
    production = deploy.split("name: Verify the activated API", 1)[1].split(
        "name: Automatically restore", 1
    )[0]

    assert 'aws s3 sync dist/ "s3://${SITE_BUCKET}/"' not in staged
    assert '"s3://${SITE_BUCKET}/releases/${RELEASE_ID}/"' in activation
    assert "previous-index-get-error.txt" in activation
    assert "NoSuchKey|Not Found|404" in activation
    assert "production static verification failed" in production
    assert '[("<root>", index_path)]' in production
    assert deploy.count('--paths "/*"') >= 5
    assert "page.on('requestfailed'" in production
    assert "workflow-restored-alias-revision.txt" in deploy
    assert "alias_restoration_safe" in deploy
    assert "refusing unsafe final compensation" in deploy
    assert "if: failure() || cancelled()" in deploy
    assert "trap 'restore_partial_activation \"$?\"' EXIT" in activation
    assert "trap 'exit 130' INT" in activation
    assert "trap 'exit 143' TERM" in activation
    assert 'exit "${original_status}"' in activation
    assert "disable_first_publication" in deploy
    assert "first-publication-service-disabled.txt" in deploy
    production_policy = iam.split(
        'data "aws_iam_policy_document" "github_production_terraform" {', 1
    )[1].split('data "aws_iam_policy_document" "github_production" {', 1)[0]
    deployment_lambda_permissions = next(
        block
        for block in production_policy.split("statement {")
        if '"lambda:PublishVersion"' in block
    )
    assert '"lambda:PutFunctionConcurrency"' in deployment_lambda_permissions
    assert (
        'resources = ["arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api*"]'
        in deployment_lambda_permissions
    )


def test_first_deploy_keeps_public_serving_private_until_candidate_gates_pass() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    serving = (ROOT / "infra/terraform/modules/platform/serving.tf").read_text(encoding="utf-8")
    observability = (ROOT / "infra/terraform/modules/platform/observability.tf").read_text(
        encoding="utf-8"
    )
    outputs = (ROOT / "infra/terraform/modules/platform/outputs.tf").read_text(encoding="utf-8")
    module_variables = (ROOT / "infra/terraform/modules/platform/variables.tf").read_text(
        encoding="utf-8"
    )

    private_reconcile = deploy.index("Reconcile the private candidate serving infrastructure")
    candidate_gate = deploy.index(
        "Run the candidate API contract, error-rate, and primary latency gates"
    )
    public_publish = deploy.index(
        "Publish the public route only after the private candidate gates pass"
    )
    static_stage = deploy.index("Build and stage the immutable static release")
    assert private_reconcile < candidate_gate < public_publish < static_stage

    private_section = deploy[private_reconcile:candidate_gate]
    public_section = deploy[public_publish:static_stage]
    assert "terraform state list" in private_section
    assert "public_serving_enabled=false" in private_section
    assert '-var="enable_public_serving=${public_serving_enabled}"' in private_section
    assert "cloudfront_distribution_id" not in private_section
    assert "cloudfront_url" not in private_section
    assert 'if [[ "${public_serving_existed}" == "false" ]]' in public_section
    assert '-var="enable_public_serving=true"' in public_section
    assert "public-serving plan unexpectedly deletes or replaces resources" in public_section
    assert "public-serving plan would mutate already-gated private resources" in public_section
    assert public_section.index("terraform apply -input=false -auto-approve public.tfplan") < (
        public_section.index("terraform output -raw cloudfront_distribution_id")
    )
    assert "trap 'fail_closed_first_publication \"$?\"' EXIT" in public_section

    assert 'variable "enable_public_serving"' in module_variables
    assert "!var.enable_public_serving || var.enable_serving" in module_variables
    public_resources = (
        "aws_apigatewayv2_api.production",
        "aws_apigatewayv2_integration.production",
        "aws_apigatewayv2_route.production",
        "aws_apigatewayv2_stage.production",
        "aws_lambda_permission.production_api",
        "aws_cloudfront_origin_access_control.site",
        "aws_cloudfront_response_headers_policy.security",
        "aws_cloudfront_function.spa_rewrite",
        "aws_cloudfront_distribution.site",
        "aws_s3_bucket_policy.site",
    )
    for resource in public_resources:
        resource_type, resource_name = resource.split(".", 1)
        block = serving.split(f'resource "{resource_type}" "{resource_name}" {{', 1)[1]
        assert "count = var.enable_public_serving ? 1 : 0" in block.split("}\n", 1)[0]
    assert (
        "count = var.enable_public_serving ? 1 : 0"
        in observability.split('resource "aws_cloudwatch_metric_alarm" "api_server_errors" {', 1)[
            1
        ].split("}\n", 1)[0]
    )
    assert "try(aws_apigatewayv2_stage.production[0].invoke_url, null)" in outputs
    assert 'try("https://${aws_cloudfront_distribution.site[0].domain_name}", null)' in outputs
    for environment in ("dev", "prod"):
        environment_root = ROOT / "infra/terraform/environments" / environment
        variables = (environment_root / "variables.tf").read_text(encoding="utf-8")
        main = (environment_root / "main.tf").read_text(encoding="utf-8")
        example = (environment_root / "terraform.tfvars.example").read_text(encoding="utf-8")
        assert 'variable "enable_public_serving"' in variables
        assert "!var.enable_public_serving || var.enable_serving" in variables
        assert "enable_public_serving             = var.enable_public_serving" in main
        assert "enable_public_serving = false" in example


def test_deploy_alarm_email_is_private_and_optional() -> None:
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    assert "TF_ALARM_NOTIFICATION_EMAIL: ${{ secrets.AWS_ALARM_NOTIFICATION_EMAIL }}" in deploy
    assert "TF_ALARM_NOTIFICATION_EMAIL: ${{ vars.AWS_ALARM_NOTIFICATION_EMAIL }}" not in deploy
