from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_training_rerun_reuses_only_the_exact_existing_job() -> None:
    workflow = (WORKFLOWS / "train.yml").read_text(encoding="utf-8")
    submission = workflow.split("name: Upload frozen configuration and submit exactly one job", 1)[
        1
    ].split("name: Wait for completion and capture sanitized evidence", 1)[0]

    assert 'run_id="${PROJECT_NAME}-${ENVIRONMENT_NAME}-${RUN_KIND}-${GITHUB_RUN_ID}"' in submission
    assert "GITHUB_RUN_ATTEMPT" not in submission
    assert submission.index("aws sagemaker describe-training-job") < submission.index(
        "aws sagemaker create-training-job"
    )
    for exact_field in (
        ".AlgorithmSpecification == $expected[0].AlgorithmSpecification",
        ".InputDataConfig == $expected[0].InputDataConfig",
        ".OutputDataConfig == $expected[0].OutputDataConfig",
        ".ResourceConfig == $expected[0].ResourceConfig",
        ".StoppingCondition == $expected[0].StoppingCondition",
        ".CheckpointConfig == $expected[0].CheckpointConfig",
        ".Environment == $expected[0].Environment",
        "($expected[0].Tags | sort_by(.Key, .Value))",
    ):
        assert exact_field in submission
    assert "InProgress|Stopping|Completed" in submission
    assert "Existing training job is terminal and unsuccessful" in submission


def test_training_inputs_and_reports_are_immutable_and_exactly_inventoried() -> None:
    workflow = (WORKFLOWS / "train.yml").read_text(encoding="utf-8")
    submission = workflow.split("put_immutable_or_verify_identical()", 1)[1].split(
        "validate_existing_training_job()", 1
    )[0]
    publication = workflow.split("publish_immutable_or_verify_identical()", 1)[1]

    for block in (submission, publication):
        assert "--if-none-match '*'" in block
        assert "--checksum-mode ENABLED" in block
        assert 'cmp -s "${source_file}" "${existing}"' in block
        assert '(.ChecksumSHA256 | type == "string" and length > 0)' in block
        assert ".Metadata ==" in block
    assert (
        '["artifact-checksums.json", "manifest.json", "train.parquet", "validation.parquet"]'
        in submission
    )
    for report in (
        "candidate-release-inputs.json",
        "cloud-training-job.json",
        "cost-preflight.json",
        "managed-spot-quota-preflight.json",
        "run-manifest.json",
        "run-manifest.sha256",
        "training-image-provenance.json",
    ):
        assert f'"{report}"' in publication
    assert ".IsTruncated != true" in publication


def test_release_counter_reservations_recover_without_double_increment() -> None:
    workflow = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    jobs = workflow.split("name: Run two separately counted clean held-out Processing jobs", 1)[
        1
    ].split("name: Verify both clean outputs", 1)[0]
    reservation = jobs.split("reserve_counter()", 1)[1].split("submit_and_wait()", 1)[0]

    assert 'base_name="${PROJECT_NAME}-${ENVIRONMENT_NAME}-release-${GITHUB_RUN_ID}"' in jobs
    assert "GITHUB_RUN_ATTEMPT" not in jobs
    assert (
        'reservation_key="runs/${base_name}/reservations/'
        'access-counter-clean-${clean_run}.json"' in reservation
    )
    assert 'if [[ "${previous}" -eq "${expected}" ]]' in reservation
    assert 'test "${expected}" -eq "$((previous + 1))"' in reservation
    assert 'write_condition=(--if-match "${current_etag}")' in reservation
    assert "write_condition=(--if-none-match '*')" in reservation
    assert 'cmp -s "counter-after-put-${clean_run}.json"' in reservation
    assert jobs.index('reserve_counter "${first_counter}" 1') < jobs.index(
        'submit_and_wait 1 "${first_counter}"'
    )
    assert jobs.index('reserve_counter "${second_counter}" 2') < jobs.index(
        'submit_and_wait 2 "${second_counter}"'
    )


def test_release_rerun_reuses_only_exact_processing_jobs() -> None:
    workflow = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    jobs = workflow.split("name: Run two separately counted clean held-out Processing jobs", 1)[
        1
    ].split("name: Verify both clean outputs", 1)[0]
    submission = jobs.split("submit_and_wait()", 1)[1]

    assert submission.index("aws sagemaker describe-processing-job") < submission.index(
        "aws sagemaker create-processing-job"
    )
    for exact_field in (
        ".AppSpecification == $expected[0].AppSpecification",
        ".ProcessingResources == $expected[0].ProcessingResources",
        ".StoppingCondition == $expected[0].StoppingCondition",
        ".ProcessingInputs == $expected[0].ProcessingInputs",
        ".ProcessingOutputConfig == $expected[0].ProcessingOutputConfig",
        ".Environment == $expected[0].Environment",
        "($expected[0].Tags | sort_by(.Key, .Value))",
    ):
        assert exact_field in submission
    assert "InProgress|Stopping|Completed" in submission
    assert "is terminal and unsuccessful" in submission


def test_release_and_freeze_publications_compare_existing_bytes_and_metadata() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    freeze = (WORKFLOWS / "freeze-trial-selection.yml").read_text(encoding="utf-8")
    public = release.split("publish_public_json()", 1)[1].split(
        'public_readback="$(mktemp -d)"', 1
    )[0]
    promoted = release.split("put_promoted_immutable_or_verify_identical()", 1)[1].split(
        "while IFS= read -r -d '' file", 1
    )[0]

    for block in (public, promoted, freeze):
        assert "--if-none-match '*'" in block
        assert "--checksum-algorithm SHA256" in block
        assert "--checksum-mode ENABLED" in block
        assert ".Metadata ==" in block
    assert 'cmp -s "${source_file}" "${existing}"' in public
    assert 'cmp -s "${source_file}" "${existing}"' in promoted
    assert "cmp -s .trial-selection/trial-selection.json" in freeze
    assert "promoted bundle S3 inventory is not exact" in release
    assert "published-public-release-objects.json" in release
    assert ".IsTruncated != true and ([.Contents[].Key] | sort) == [$key]" in freeze


def test_image_build_reruns_reuse_only_exactly_bound_immutable_images() -> None:
    workflow = (WORKFLOWS / "build-images.yml").read_text(encoding="utf-8")
    build = workflow.split("name: Build, push, and capture immutable digests", 1)[1]
    verification = build.split("verify_remote_binding()", 1)[1].split(
        "for kind in train eval serve", 1
    )[0]
    loop = build.split("for kind in train eval serve", 1)[1].split(
        "- uses: actions/upload-artifact", 1
    )[0]

    # The binding covers the exact tracked tree, commit, and per-image Dockerfile.
    assert 'subprocess.check_output(["git", "ls-files", "-z"])' in build
    assert 'open(raw_path, "rb").read()' in build
    assert 'docker pull "${repository}@${digest}"' in verification
    for label in (
        "org.opencontainers.image.revision",
        "io.product-search.source-tree-sha256",
        "io.product-search.dockerfile-sha256",
    ):
        assert label in verification
        assert f'--label "{label}=' in loop

    lookup = loop.index("aws ecr describe-images")
    reuse = loop.index(
        'echo "Reusing the exact immutable ${kind} image bound to this source tree."'
    )
    build_image = loop.index("docker build", reuse)
    push = loop.index('docker push "${repository}:${tag}"', build_image)
    race_lookup = loop.index('> "${kind}-race-image.json"', push)
    final_verification = loop.rindex(
        'verify_remote_binding "${repository}" "${digest}" "${dockerfile_hash}"'
    )

    assert lookup < loop.index("verify_remote_binding", lookup) < reuse
    assert reuse < build_image < push < race_lookup < final_verification
    assert "ImageNotFoundException" in loop[lookup:build_image]
    assert "An immutable-tag race is acceptable only when the winner has the exact labels" in loop
    assert 'digest="$(jq -er' in loop[push:final_verification]
    assert 'test "${digest#sha256:}" != "${digest}"' in loop


def test_baseline_bootstrap_recovers_identical_partial_uploads_before_pointer_cas() -> None:
    workflow = (WORKFLOWS / "bootstrap-baseline.yml").read_text(encoding="utf-8")
    publication = workflow.split(
        "name: Publish the immutable baseline bundle and create the initial pointer", 1
    )[1]
    bundle_put = publication.split("put_immutable_or_verify_identical()", 1)[1].split(
        "while IFS= read -r -d '' file", 1
    )[0]
    inventory = publication.split("aws s3api list-objects-v2", 1)[1].split("jq -n \\", 1)[0]
    pointer = publication.split("--key promoted/current.json", 1)[1]

    assert "--if-none-match '*'" in bundle_put
    assert bundle_put.index("aws s3api put-object") < bundle_put.index("aws s3api get-object")
    assert 'cmp -s "${source_file}" "${existing_file}"' in bundle_put
    assert "--checksum-mode ENABLED" in bundle_put
    assert '.ChecksumSHA256 | type == "string" and length > 0' in bundle_put
    assert '.TagSet == [{Key: "RetentionClass", Value: "promoted"}]' in bundle_put
    assert "prefix must be empty" not in publication.lower()

    assert "--no-paginate" in inventory
    assert 'prefix + path.relative_to(".baseline-release").as_posix()' in inventory
    assert 'actual = sorted(item["Key"] for item in payload.get("Contents", []))' in inventory
    assert 'payload.get("IsTruncated") is True or actual != expected' in inventory
    assert "baseline bundle prefix inventory is not exact" in inventory

    inventory_position = publication.index("baseline bundle prefix inventory is not exact")
    pointer_position = publication.index("--key promoted/current.json")
    assert inventory_position < pointer_position
    assert "--if-none-match '*'" in pointer
    assert "--checksum-mode ENABLED" in pointer
    assert (
        'cmp -s baseline-promotion-pointer.json "${readback_dir}/existing-pointer.json"' in pointer
    )


def test_every_post_bootstrap_aws_job_reserves_shared_capacity_immediately_after_oidc() -> None:
    workflow_jobs = {
        "baseline.yml": ("baseline",),
        "benchmark-serving.yml": ("benchmark",),
        "bootstrap-baseline.yml": ("publish",),
        "build-images.yml": ("build-and-push",),
        "deploy.yml": ("deploy", "rollback"),
        "freeze-trial-selection.yml": ("freeze",),
        "infrastructure.yml": ("terraform",),
        "prepare-data.yml": ("prepare-and-publish",),
        "release.yml": ("evaluate-and-promote",),
        "train.yml": ("submit",),
    }
    protected_reservation_environment = {
        "FINANCIAL_RESERVATION_MAX_USD": "${{ secrets.AWS_FINANCIAL_RESERVATION_MAX_USD }}",
        "FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD": (
            "${{ secrets.AWS_FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD }}"
        ),
        "FINANCIAL_RESERVATION_CPU_HOURS": ("${{ secrets.AWS_FINANCIAL_RESERVATION_CPU_HOURS }}"),
        "FINANCIAL_RESERVATION_GPU_HOURS": ("${{ secrets.AWS_FINANCIAL_RESERVATION_GPU_HOURS }}"),
        "FINANCIAL_CPU_HOURS_USED_TO_DATE": ("${{ secrets.AWS_FINANCIAL_CPU_HOURS_USED_TO_DATE }}"),
        "FINANCIAL_GPU_HOURS_USED_TO_DATE": ("${{ secrets.AWS_FINANCIAL_GPU_HOURS_USED_TO_DATE }}"),
        "TF_STATE_BUCKET": "${{ vars.AWS_TERRAFORM_STATE_BUCKET }}",
    }

    for workflow_name, job_names in workflow_jobs.items():
        payload = yaml.safe_load((WORKFLOWS / workflow_name).read_text(encoding="utf-8"))
        assert payload["concurrency"] == {
            "group": "aws-financial-operations",
            "cancel-in-progress": False,
        }, workflow_name
        for job_name in job_names:
            job = payload["jobs"][job_name]
            for key, value in protected_reservation_environment.items():
                assert job["env"].get(key) == value, (workflow_name, job_name, key)

            credential_positions = [
                index
                for index, step in enumerate(job["steps"])
                if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials@")
            ]
            reservation_positions = [
                index
                for index, step in enumerate(job["steps"])
                if step.get("name") == "Atomically reserve the signed campaign capacity"
            ]
            assert len(credential_positions) == len(reservation_positions) == 1, (
                workflow_name,
                job_name,
            )
            assert reservation_positions[0] == credential_positions[0] + 1, (
                workflow_name,
                job_name,
            )
            reservation = job["steps"][reservation_positions[0]]["run"]
            assert "scripts/reserve_financial_capacity.py reserve" in reservation
            assert '--bucket "${TF_STATE_BUCKET}"' in reservation
            assert "--output financial-capacity-reservation.json" in reservation


def test_state_bootstrap_is_serialized_and_initializes_the_cas_ledger() -> None:
    payload = yaml.safe_load(
        (WORKFLOWS / "bootstrap-infrastructure.yml").read_text(encoding="utf-8")
    )
    assert payload["concurrency"] == {
        "group": "aws-financial-operations",
        "cancel-in-progress": False,
    }
    job = payload["jobs"]["bootstrap"]
    assert job["environment"] == "aws-state-bootstrap"
    for name, value in {
        "FINANCIAL_RESERVATION_MAX_USD": "0.10",
        "FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD": "0",
        "FINANCIAL_RESERVATION_CPU_HOURS": "0",
        "FINANCIAL_RESERVATION_GPU_HOURS": "0",
        "FINANCIAL_CPU_HOURS_USED_TO_DATE": "0",
        "FINANCIAL_GPU_HOURS_USED_TO_DATE": "0",
    }.items():
        assert job["env"][name] == value
    steps = job["steps"]
    credential_steps = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials@")
    ]
    assert len(credential_steps) == 1
    assert credential_steps[0]["with"]["role-to-assume"] == ("${{ vars.AWS_BOOTSTRAP_ROLE_ARN }}")
    initialization = "\n".join(step.get("run", "") for step in steps)
    assert "scripts/reserve_financial_capacity.py init" in initialization
    assert '--bucket "${STATE_BUCKET}"' in initialization


def test_oidc_subjects_and_roles_are_bound_to_exact_workflow_environments() -> None:
    workflow_environments = {
        "baseline.yml": (("baseline",), "aws-baseline"),
        "benchmark-serving.yml": (("benchmark",), "production-benchmark"),
        "bootstrap-baseline.yml": (("publish",), "baseline-release"),
        "build-images.yml": (("build-and-push",), "aws-images"),
        "deploy.yml": (("deploy", "rollback"), "production"),
        "freeze-trial-selection.yml": (("freeze",), "aws-trial-selection"),
        "infrastructure.yml": (("terraform",), "aws-infrastructure"),
        "prepare-data.yml": (("prepare-and-publish",), "aws-data"),
        "release.yml": (("evaluate-and-promote",), "heldout-release"),
        "train.yml": (("submit",), "aws-training"),
    }
    for workflow_name, (job_names, environment) in workflow_environments.items():
        payload = yaml.safe_load((WORKFLOWS / workflow_name).read_text(encoding="utf-8"))
        for job_name in job_names:
            assert payload["jobs"][job_name]["environment"] == environment, (
                workflow_name,
                job_name,
            )

    special_roles = {
        "baseline.yml": ("baseline", "${{ vars.AWS_BASELINE_ROLE_ARN }}"),
        "benchmark-serving.yml": (
            "benchmark",
            "${{ vars.AWS_BENCHMARK_ROLE_ARN }}",
        ),
        "freeze-trial-selection.yml": (
            "freeze",
            "${{ vars.AWS_TRIAL_SELECTION_ROLE_ARN }}",
        ),
    }
    for workflow_name, (job_name, role) in special_roles.items():
        payload = yaml.safe_load((WORKFLOWS / workflow_name).read_text(encoding="utf-8"))
        credential_steps = [
            step
            for step in payload["jobs"][job_name]["steps"]
            if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials@")
        ]
        assert len(credential_steps) == 1
        assert credential_steps[0]["with"]["role-to-assume"] == role

    locals_source = (ROOT / "infra" / "terraform" / "modules" / "platform" / "locals.tf").read_text(
        encoding="utf-8"
    )
    mapping_block = locals_source.split("github_environment_workflow_files = {", 1)[1].split(
        "\n  }", 1
    )[0]
    actual_mapping = {}
    for line in mapping_block.splitlines():
        if "=" not in line:
            continue
        environment, workflow_name = (part.strip() for part in line.split("=", 1))
        actual_mapping[environment] = workflow_name.strip('"')
    expected_mapping = {
        environment: workflow_name
        for workflow_name, (_, environment) in workflow_environments.items()
    }
    assert actual_mapping == expected_mapping

    iam = (ROOT / "infra" / "terraform" / "modules" / "platform" / "iam.tf").read_text(
        encoding="utf-8"
    )
    assert ":workflow_ref:${var.github_repository}/.github/workflows/" in iam
    assert "job_workflow_ref" not in iam
    assert "${local.github_environment_workflow_files[each.key]}@refs/heads/main" in iam
    assert '${local.github_environment_workflow_files["production"]}@refs/heads/main' in iam

    deployment_guide = (ROOT / "docs" / "cloud-deployment.md").read_text(encoding="utf-8")
    assert 'include_claim_keys = @("repo", "environment", "workflow_ref")' in deployment_guide
    assert '"repo,environment,workflow_ref"' in deployment_guide
    assert "job_workflow_ref" not in deployment_guide

    for policy, environment in (
        ("github_baseline", "aws-baseline"),
        ("github_trial_selection", "aws-trial-selection"),
        ("github_benchmark", "production-benchmark"),
    ):
        policy_body = iam.split(f'data "aws_iam_policy_document" "{policy}"', 1)[1].split(
            f'resource "aws_iam_role_policy" "{policy}"', 1
        )[0]
        attachment = iam.split(f'resource "aws_iam_role_policy" "{policy}"', 1)[1].split("\n}", 1)[
            0
        ]
        assert "sagemaker:" not in policy_body
        assert f'aws_iam_role.github_workflow["{environment}"].id' in attachment

    benchmark_policy = iam.split('data "aws_iam_policy_document" "github_benchmark"', 1)[1].split(
        'resource "aws_iam_role_policy" "github_benchmark"', 1
    )[0]
    for forbidden_action in (
        "cloudfront:UpdateDistribution",
        "ecr:",
        "lambda:UpdateAlias",
        "lambda:UpdateFunctionCode",
        "s3:DeleteObject",
    ):
        assert forbidden_action not in benchmark_policy
