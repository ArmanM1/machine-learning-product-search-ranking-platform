from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CREDENTIAL_ACTION = "aws-actions/configure-aws-credentials@"


def _workflow(name: str) -> dict[str, object]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _step_index(steps: list[dict[str, object]], name: str) -> int:
    return next(index for index, step in enumerate(steps) if step.get("name") == name)


def _is_credentials(step: dict[str, object]) -> bool:
    return str(step.get("uses", "")).startswith(CREDENTIAL_ACTION)


def test_release_runs_one_clean_evaluation_per_sequential_job() -> None:
    release = _workflow("release.yml")
    jobs = release["jobs"]

    assert list(jobs) == [
        "prepare",
        "clean-evaluation-1",
        "clean-evaluation-2",
        "finalize",
    ]
    assert jobs["clean-evaluation-1"]["needs"] == "prepare"
    assert jobs["clean-evaluation-2"]["needs"] == "clean-evaluation-1"
    assert jobs["finalize"]["needs"] == "clean-evaluation-2"
    for ordinal in (1, 2):
        job = jobs[f"clean-evaluation-{ordinal}"]
        assert job["uses"] == "./.github/workflows/release-clean-evaluation.yml"
        assert job["with"]["clean_run"] == ordinal


def test_each_clean_job_refreshes_oidc_for_bounded_poll_windows() -> None:
    reusable = _workflow("release-clean-evaluation.yml")
    job = reusable["jobs"]["evaluate"]
    steps = job["steps"]

    assert job["timeout-minutes"] == 300
    assert int(job["env"]["POLL_WINDOW_SECONDS"]) < 3600
    assert int(job["env"]["POLL_INTERVAL_SECONDS"]) <= 60
    credential_indexes = [index for index, step in enumerate(steps) if _is_credentials(step)]
    assert len(credential_indexes) == 7

    for window in range(1, 6):
        poll_index = _step_index(steps, f"Poll clean evaluation in bounded window {window}")
        assert _is_credentials(steps[poll_index - 1])
        assert steps[poll_index]["run"] == (
            'bash scripts/release_processing_phase.sh poll "${{ inputs.clean_run }}"'
        )

    collect_index = _step_index(steps, "Collect the terminal clean-evaluation evidence")
    assert _is_credentials(steps[collect_index - 1])
    assert steps[collect_index]["run"] == (
        'bash scripts/release_processing_phase.sh collect "${{ inputs.clean_run }}"'
    )


def test_release_refreshes_oidc_before_every_publication_phase() -> None:
    release = _workflow("release.yml")
    prepare_steps = release["jobs"]["prepare"]["steps"]
    stage_index = _step_index(
        prepare_steps, "Stage immutable inputs shared by both clean evaluations"
    )
    assert _is_credentials(prepare_steps[stage_index - 1])

    final_steps = release["jobs"]["finalize"]["steps"]
    reservation_index = _step_index(final_steps, "Atomically reserve the signed campaign capacity")
    assert _is_credentials(final_steps[reservation_index - 1])
    assert "scripts/reserve_financial_capacity.py reserve" in final_steps[reservation_index]["run"]
    bind_index = _step_index(
        final_steps,
        "Verify both clean outputs, bind them, and apply the promotion decision",
    )
    publish_index = _step_index(
        final_steps,
        "Build and publish the checksummed held-out outcome bundle",
    )
    assert _is_credentials(final_steps[bind_index - 1])
    assert _is_credentials(final_steps[publish_index - 1])

    reusable_steps = _workflow("release-clean-evaluation.yml")["jobs"]["evaluate"]["steps"]
    phase_reservation_index = _step_index(
        reusable_steps, "Atomically reserve the signed campaign capacity"
    )
    assert _is_credentials(reusable_steps[phase_reservation_index - 1])
    assert (
        "scripts/reserve_financial_capacity.py reserve"
        in (reusable_steps[phase_reservation_index]["run"])
    )
    submit_index = _step_index(
        reusable_steps,
        "Reserve one access and submit or reuse the exact clean evaluation",
    )
    assert phase_reservation_index < submit_index


def test_processing_phase_is_bounded_idempotent_and_split_sha_bound() -> None:
    phase = (ROOT / "scripts" / "release_processing_phase.sh").read_text(encoding="utf-8")

    assert "(( MAX_TIMEOUT_SECONDS <= 14400 ))" in phase
    assert "(( window_seconds <= 3000 ))" in phase
    assert phase.count("aws sagemaker create-processing-job") == 1
    assert "wait processing-job-completed" not in phase
    assert "GITHUB_RUN_ATTEMPT" not in phase
    assert 'job_name="${base_name}-clean-${clean_run}"' in phase
    assert 'counter="$((TEST_ACCESS_COUNTER + clean_run - 1))"' in phase
    assert ".AppSpecification == $expected[0].AppSpecification" in phase
    assert ".ProcessingResources == $expected[0].ProcessingResources" in phase
    assert ".StoppingCondition == $expected[0].StoppingCondition" in phase
    assert ".ProcessingInputs == $expected[0].ProcessingInputs" in phase
    assert ".ProcessingOutputConfig == $expected[0].ProcessingOutputConfig" in phase
    assert ".Environment == $expected[0].Environment" in phase
    assert "MODEL_SOURCE_GIT_SHA: $model_source_commit" in phase
    assert "SEARCH_RANK_GIT_SHA: $commit" in phase
    assert "release_git_sha: $release_git_sha" in phase
    assert "model_source_git_sha: $model_source_git_sha" in phase


def test_release_does_not_activate_production_or_reopen_heldout_in_finalizer() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    finalizer = release.split("  finalize:", 1)[1]

    assert "aws sagemaker create-processing-job" not in release
    assert "terraform apply" not in release
    assert "aws lambda update" not in release
    assert "aws apigateway" not in release
    assert "promoted/current.json" not in finalizer
    assert "heldout-clean-1-${{ github.run_id }}" in finalizer
    assert "heldout-clean-2-${{ github.run_id }}" in finalizer
