#!/usr/bin/env bash
# Retry-safe lifecycle for exactly one held-out SageMaker Processing evaluation.

set -euo pipefail

mode="${1:-}"
clean_run="${2:-}"
if [[ "${mode}" != "reserve-submit" && "${mode}" != "poll" && "${mode}" != "collect" ]]; then
  echo "usage: release_processing_phase.sh {reserve-submit|poll|collect} {1|2}" >&2
  exit 2
fi
if [[ "${clean_run}" != "1" && "${clean_run}" != "2" ]]; then
  echo "clean-run ordinal must be 1 or 2" >&2
  exit 2
fi

for name in \
  ARTIFACT_BUCKET AWS_REGION BASELINE_CONFIG_HASH BASELINE_IDS \
  CANDIDATE_ARTIFACT_S3_URI CANDIDATE_CHECKPOINT_SHA256 CANDIDATE_CONFIG_SHA256 \
  CANDIDATE_MODEL_ID CANDIDATE_RUN_ID EVALUATION_IMAGE_URI GITHUB_RUN_ID GITHUB_SHA \
  HELDOUT_DATA_S3_URI INSTANCE_TYPE MAX_TIMEOUT_SECONDS MODEL_SOURCE_GIT_SHA \
  OWNER_ALIAS PROCESSING_ROLE_ARN PROJECT_NAME ENVIRONMENT_NAME STRONGEST_BASELINE_ID \
  TEST_ACCESS_COUNTER; do
  if [[ -z "${!name:-}" ]]; then
    echo "required release environment is incomplete" >&2
    exit 2
  fi
done
[[ "${GITHUB_SHA}" =~ ^[0-9a-f]{40}$ ]]
[[ "${MODEL_SOURCE_GIT_SHA}" =~ ^[0-9a-f]{40}$ ]]
[[ "${TEST_ACCESS_COUNTER}" =~ ^[1-9][0-9]*$ ]]
[[ "${MAX_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]
(( MAX_TIMEOUT_SECONDS <= 14400 ))
(( TEST_ACCESS_COUNTER <= 999999 ))

run_token="h$(printf '%s' "${GITHUB_RUN_ID}" | sha256sum | cut -c1-16)"
base_name="${PROJECT_NAME}-${ENVIRONMENT_NAME}-release-${run_token}"
base_name="${base_name:0:55}"
job_name="${base_name}-clean-${clean_run}"
counter="$((TEST_ACCESS_COUNTER + clean_run - 1))"
output_uri="s3://${ARTIFACT_BUCKET}/runs/${job_name}/reports/"
shared_prefix="s3://${ARTIFACT_BUCKET}/runs/${base_name}/shared/"
request_path="processing-job-clean-${clean_run}.json"
handoff_path="processing-phase-clean-${clean_run}.json"

verify_financial_snapshot() {
  PYTHONPATH=src uv run python scripts/validate_financial_snapshot.py verify \
    --cost-preflight cost-preflight.json
}

put_immutable_or_verify_identical() {
  local source_file="$1"
  local object_key="$2"
  local readback head put_error local_sha stem
  local_sha="sha256:$(sha256sum "${source_file}" | cut -d' ' -f1)"
  stem="$(printf '%s' "${object_key}" | sha256sum | cut -d' ' -f1)"
  readback="phase-readback-${clean_run}-${stem}.json"
  head="phase-head-${clean_run}-${stem}.json"
  put_error="phase-put-${clean_run}-${stem}.error"
  verify_financial_snapshot
  if ! aws s3api put-object \
    --bucket "${ARTIFACT_BUCKET}" \
    --key "${object_key}" \
    --body "${source_file}" \
    --content-type application/json \
    --checksum-algorithm SHA256 \
    --metadata "sha256=${local_sha},retention-class=candidate" \
    --tagging 'RetentionClass=candidate' \
    --if-none-match '*' >/dev/null 2>"${put_error}"; then
    : # Exact partial writes are recoverable and verified below.
  fi
  if ! aws s3api get-object \
    --bucket "${ARTIFACT_BUCKET}" \
    --key "${object_key}" \
    --checksum-mode ENABLED \
    "${readback}" >/dev/null 2>&1 || ! cmp -s "${source_file}" "${readback}"; then
    echo "immutable held-out phase object differs" >&2
    return 1
  fi
  aws s3api head-object \
    --bucket "${ARTIFACT_BUCKET}" \
    --key "${object_key}" \
    --checksum-mode ENABLED >"${head}"
  jq -e --arg sha "${local_sha}" '
    .ContentType == "application/json" and
    (.ChecksumSHA256 | type == "string" and length > 0) and
    .Metadata == {"retention-class": "candidate", sha256: $sha}' \
    "${head}" >/dev/null
  rm -f -- "${readback}" "${head}" "${put_error}"
}

reserve_counter() {
  local reservation_key="runs/${base_name}/reservations/access-counter-clean-${clean_run}.json"
  local counter_key="heldout/access-counter.json"
  local counter_size_base=4096
  local current_size expected_size previous version_count latest_count latest_size
  local local_md5 content_md5 checksum_sha256 expected_etag put_version_id
  local write_condition=()

  jq -n \
    --argjson count "${counter}" \
    --argjson clean_run "${clean_run}" \
    --arg run "${CANDIDATE_RUN_ID}" \
    --arg commit "${GITHUB_SHA}" \
    --arg workflow_run "${GITHUB_RUN_ID}" \
    '{schema_version: "1.0.0", artifact_type: "heldout_access_counter",
      count: $count, clean_run: $clean_run, candidate_run_id: $run,
      code_commit: $commit, workflow_run_id: $workflow_run}' \
    >"access-counter-clean-${clean_run}.json"
  current_size="$(wc -c <"access-counter-clean-${clean_run}.json")"
  expected_size="$((counter_size_base + counter))"
  (( current_size < expected_size ))
  printf '%*s' "$((expected_size - current_size))" '' \
    >>"access-counter-clean-${clean_run}.json"
  [[ "$(wc -c <"access-counter-clean-${clean_run}.json")" -eq "${expected_size}" ]]
  uv run python scripts/validate_release_artifacts.py file \
    --kind access-counter "access-counter-clean-${clean_run}.json"
  local_md5="$(md5sum "access-counter-clean-${clean_run}.json" | cut -d' ' -f1)"
  content_md5="$(openssl dgst -md5 -binary "access-counter-clean-${clean_run}.json" | base64 -w0)"
  checksum_sha256="$(openssl dgst -sha256 -binary "access-counter-clean-${clean_run}.json" | base64 -w0)"
  expected_etag="\"${local_md5}\""

  if aws s3api head-object \
    --bucket "${ARTIFACT_BUCKET}" \
    --key "${reservation_key}" >"reservation-head-${clean_run}.json" \
    2>"reservation-head-${clean_run}.error"; then
    put_immutable_or_verify_identical \
      "access-counter-clean-${clean_run}.json" "${reservation_key}"
    return 0
  elif ! grep -Eq '(404|Not Found|NoSuchKey)' "reservation-head-${clean_run}.error"; then
    echo "held-out counter reservation lookup failed" >&2
    return 1
  fi

  aws s3api get-bucket-versioning \
    --bucket "${ARTIFACT_BUCKET}" >"counter-bucket-versioning-${clean_run}.json"
  jq -e '.Status == "Enabled"' "counter-bucket-versioning-${clean_run}.json" >/dev/null
  aws s3api list-object-versions \
    --bucket "${ARTIFACT_BUCKET}" \
    --prefix "${counter_key}" >"counter-versions-before-${clean_run}.json"
  jq -e --arg key "${counter_key}" '
    .IsTruncated != true and
    ([.Versions[]? | select(.Key != $key)] | length) == 0 and
    ([.DeleteMarkers[]?] | length) == 0' \
    "counter-versions-before-${clean_run}.json" >/dev/null
  version_count="$(jq -r '[.Versions[]?] | length' "counter-versions-before-${clean_run}.json")"
  latest_count="$(jq -r --arg key "${counter_key}" \
    '[.Versions[]? | select(.Key == $key and .IsLatest == true)] | length' \
    "counter-versions-before-${clean_run}.json")"
  if [[ "${version_count}" -eq 0 ]]; then
    [[ "${latest_count}" -eq 0 ]]
    previous=0
    write_condition=(--if-none-match '*')
  else
    [[ "${latest_count}" -eq 1 ]]
    jq -e --arg key "${counter_key}" '
      [.Versions[]? | select(.Key == $key and .IsLatest == true)][0] |
      (.VersionId | type == "string" and length > 0 and . != "null") and
      (.ETag | type == "string" and test("^\\\"[0-9a-f]{32}\\\"$")) and
      (.Size | type == "number") and
      ((.ChecksumAlgorithm // []) | index("SHA256") != null)' \
      "counter-versions-before-${clean_run}.json" >/dev/null
    latest_size="$(jq -er --arg key "${counter_key}" \
      '[.Versions[]? | select(.Key == $key and .IsLatest == true)][0].Size' \
      "counter-versions-before-${clean_run}.json")"
    previous="$((latest_size - counter_size_base))"
    (( previous >= 1 ))
  fi

  if [[ "${previous}" -eq "${counter}" ]]; then
    jq -e \
      --arg key "${counter_key}" \
      --arg etag "${expected_etag}" \
      --argjson size "${expected_size}" '
      [.Versions[]? | select(.Key == $key and .IsLatest == true)][0] |
      .ETag == $etag and .Size == $size and
      ((.ChecksumAlgorithm // []) | index("SHA256") != null)' \
      "counter-versions-before-${clean_run}.json" >/dev/null
    put_immutable_or_verify_identical \
      "access-counter-clean-${clean_run}.json" "${reservation_key}"
    return 0
  fi
  if [[ "${counter}" -ne "$((previous + 1))" ]]; then
    echo "held-out counter is not the exact next value" >&2
    return 1
  fi

  verify_financial_snapshot
  if aws s3api put-object \
    --bucket "${ARTIFACT_BUCKET}" \
    --key "${counter_key}" \
    --body "access-counter-clean-${clean_run}.json" \
    --content-type application/json \
    --content-md5 "${content_md5}" \
    --server-side-encryption AES256 \
    --checksum-algorithm SHA256 \
    --checksum-sha256 "${checksum_sha256}" \
    --metadata "counter-size-base=${counter_size_base},workflow-run-id=${GITHUB_RUN_ID},clean-run=${clean_run}" \
    "${write_condition[@]}" >"counter-put-${clean_run}.json" \
    2>"counter-put-${clean_run}.error"; then
    jq -e --arg checksum "${checksum_sha256}" --arg etag "${expected_etag}" '
      .ChecksumSHA256 == $checksum and .ETag == $etag and
      .ServerSideEncryption == "AES256" and
      (.VersionId | type == "string" and length > 0 and . != "null")' \
      "counter-put-${clean_run}.json" >/dev/null
    put_version_id="$(jq -er '.VersionId' "counter-put-${clean_run}.json")"
  else
    put_version_id=""
  fi
  aws s3api list-object-versions \
    --bucket "${ARTIFACT_BUCKET}" \
    --prefix "${counter_key}" >"counter-versions-after-${clean_run}.json"
  jq -e \
    --arg key "${counter_key}" \
    --arg etag "${expected_etag}" \
    --arg version "${put_version_id}" \
    --argjson size "${expected_size}" '
    .IsTruncated != true and
    ([.Versions[]? | select(.Key != $key)] | length) == 0 and
    ([.DeleteMarkers[]?] | length) == 0 and
    ([.Versions[]? | select(.Key == $key and .IsLatest == true)] | length) == 1 and
    ([.Versions[]? | select(.Key == $key and .IsLatest == true)][0] |
      (.VersionId | type == "string" and length > 0 and . != "null") and
      .ETag == $etag and .Size == $size and
      ((.ChecksumAlgorithm // []) | index("SHA256") != null) and
      ($version == "" or .VersionId == $version))' \
    "counter-versions-after-${clean_run}.json" >/dev/null || {
      echo "held-out counter publication could not be proven" >&2
      return 1
    }
  put_immutable_or_verify_identical \
    "access-counter-clean-${clean_run}.json" "${reservation_key}"
}

build_request() {
  local image_digest="${EVALUATION_IMAGE_URI##*@}"
  jq -n \
    --arg job "${job_name}" \
    --arg role "${PROCESSING_ROLE_ARN}" \
    --arg image "${EVALUATION_IMAGE_URI}" \
    --arg image_digest "${image_digest}" \
    --arg instance "${INSTANCE_TYPE}" \
    --arg config "${shared_prefix}evaluation/" \
    --arg candidate_config "${shared_prefix}candidate-config/" \
    --arg baseline "${shared_prefix}baseline/" \
    --arg data "${HELDOUT_DATA_S3_URI}" \
    --arg model "${CANDIDATE_ARTIFACT_S3_URI}" \
    --arg output "${output_uri}" \
    --arg candidate_run "${CANDIDATE_RUN_ID}" \
    --arg candidate_model "${CANDIDATE_MODEL_ID}" \
    --arg candidate_hash "${CANDIDATE_CHECKPOINT_SHA256}" \
    --arg candidate_config_hash "${CANDIDATE_CONFIG_SHA256}" \
    --arg config_hash "${FROZEN_CONFIG_SHA256}" \
    --arg dataset_hash "${DATASET_MANIFEST_HASH}" \
    --arg baselines "${BASELINE_IDS}" \
    --arg strongest_baseline "${STRONGEST_BASELINE_ID}" \
    --arg baseline_config_hash "${BASELINE_CONFIG_HASH}" \
    --arg counter "${counter}" \
    --arg clean_run "${clean_run}" \
    --arg commit "${GITHUB_SHA}" \
    --arg model_source_commit "${MODEL_SOURCE_GIT_SHA}" \
    --arg region "${AWS_REGION}" \
    --arg project "${PROJECT_NAME}" \
    --arg environment "${ENVIRONMENT_NAME}" \
    --arg owner "${OWNER_ALIAS}" \
    --argjson timeout "${MAX_TIMEOUT_SECONDS}" '
    {
      ProcessingJobName: $job,
      RoleArn: $role,
      AppSpecification: {
        ImageUri: $image,
        ContainerEntrypoint: ["python", "/app/scripts/container_eval.py"],
        ContainerArguments: [
          "--config", "/opt/ml/processing/input/config/release.yaml",
          "--heldout",
          "--candidate-bundle", "/opt/ml/processing/input/candidate",
          "--candidate-config", "/opt/ml/processing/input/candidate-config/frozen-candidate.yaml",
          "--heldout-input", "/opt/ml/processing/input/heldout",
          "--baseline-summary", "/opt/ml/processing/input/baseline",
          "--strongest-baseline-id", $strongest_baseline,
          "--test-access-counter", $counter,
          "--candidate-checkpoint-sha256", $candidate_hash,
          "--candidate-config-sha256", $candidate_config_hash,
          "--dataset-processed-sha256", $dataset_hash
        ]
      },
      ProcessingResources: {ClusterConfig: {
        InstanceCount: 1, InstanceType: $instance, VolumeSizeInGB: 30
      }},
      StoppingCondition: {MaxRuntimeInSeconds: $timeout},
      ProcessingInputs: [
        {InputName: "config", S3Input: {S3Uri: $config, LocalPath: "/opt/ml/processing/input/config", S3DataType: "S3Prefix", S3InputMode: "File"}},
        {InputName: "candidate-config", S3Input: {S3Uri: $candidate_config, LocalPath: "/opt/ml/processing/input/candidate-config", S3DataType: "S3Prefix", S3InputMode: "File"}},
        {InputName: "baseline", S3Input: {S3Uri: $baseline, LocalPath: "/opt/ml/processing/input/baseline", S3DataType: "S3Prefix", S3InputMode: "File"}},
        {InputName: "heldout", S3Input: {S3Uri: $data, LocalPath: "/opt/ml/processing/input/heldout", S3DataType: "S3Prefix", S3InputMode: "File"}},
        {InputName: "candidate", S3Input: {S3Uri: $model, LocalPath: "/opt/ml/processing/input/candidate", S3DataType: "S3Prefix", S3InputMode: "File"}}
      ],
      ProcessingOutputConfig: {Outputs: [{OutputName: "reports", S3Output: {
        S3Uri: $output, LocalPath: "/opt/ml/processing/output", S3UploadMode: "EndOfJob"
      }}]},
      Environment: {
        ALLOW_HELDOUT_EVAL: "1",
        CANDIDATE_RUN_ID: $candidate_run,
        CANDIDATE_MODEL_ID: $candidate_model,
        CANDIDATE_CHECKPOINT_SHA256: $candidate_hash,
        CANDIDATE_CONFIG_SHA256: $candidate_config_hash,
        FROZEN_CONFIG_SHA256: $config_hash,
        DATASET_MANIFEST_HASH: $dataset_hash,
        BASELINE_IDS: $baselines,
        STRONGEST_BASELINE_ID: $strongest_baseline,
        VALIDATION_BASELINE_CONFIG_HASH: $baseline_config_hash,
        TEST_ACCESS_COUNTER: $counter,
        CLEAN_RUN_ORDINAL: $clean_run,
        CODE_COMMIT: $commit,
        MODEL_SOURCE_GIT_SHA: $model_source_commit,
        SEARCH_RANK_EVALUATION_IMAGE_DIGEST: $image_digest,
        SEARCH_RANK_HARDWARE_CLASS: $instance,
        SEARCH_RANK_GIT_SHA: $commit,
        AWS_REGION: $region
      },
      Tags: [
        {Key: "Project", Value: $project},
        {Key: "Environment", Value: $environment},
        {Key: "Owner", Value: $owner},
        {Key: "RunId", Value: $job},
        {Key: "CleanRun", Value: $clean_run},
        {Key: "HeldoutAccessCounter", Value: $counter},
        {Key: "ModelSourceGitSha", Value: $model_source_commit}
      ]
    }' >"${request_path}"
}

validate_existing_job() {
  local description="$1"
  local arn status
  jq -e --slurpfile expected "${request_path}" '
    .ProcessingJobName == $expected[0].ProcessingJobName and
    .RoleArn == $expected[0].RoleArn and
    .AppSpecification == $expected[0].AppSpecification and
    .ProcessingResources == $expected[0].ProcessingResources and
    .StoppingCondition == $expected[0].StoppingCondition and
    .ProcessingInputs == $expected[0].ProcessingInputs and
    .ProcessingOutputConfig == $expected[0].ProcessingOutputConfig and
    .Environment == $expected[0].Environment' "${description}" >/dev/null
  arn="$(jq -er '.ProcessingJobArn' "${description}")"
  aws sagemaker list-tags --resource-arn "${arn}" >"existing-processing-tags-clean-${clean_run}.json"
  jq -e --slurpfile expected "${request_path}" '
    (.Tags | sort_by(.Key, .Value)) == ($expected[0].Tags | sort_by(.Key, .Value))' \
    "existing-processing-tags-clean-${clean_run}.json" >/dev/null
  status="$(jq -er '.ProcessingJobStatus' "${description}")"
  case "${status}" in
    InProgress|Stopping|Completed) ;;
    Failed|Stopped)
      echo "existing held-out evaluation is terminal and unsuccessful" >&2
      return 1
      ;;
    *) echo "held-out evaluation returned an unexpected state" >&2; return 1 ;;
  esac
}

write_handoff() {
  jq -n \
    --argjson clean_run "${clean_run}" \
    --argjson counter "${counter}" \
    --arg release_git_sha "${GITHUB_SHA}" \
    --arg model_source_git_sha "${MODEL_SOURCE_GIT_SHA}" \
    --arg job_name "${job_name}" \
    --arg output_uri "${output_uri}" \
    --arg request_sha256 "sha256:$(sha256sum "${request_path}" | cut -d' ' -f1)" \
    '{schema_version: "1.0.0", artifact_type: "heldout_processing_phase",
      clean_run: $clean_run, test_access_counter: $counter,
      release_git_sha: $release_git_sha, model_source_git_sha: $model_source_git_sha,
      processing_job_name: $job_name, output_uri: $output_uri,
      request_sha256: $request_sha256}' >"${handoff_path}"
  printf '%s' "${output_uri}" >"output-uri-clean-${clean_run}.txt"
}

verify_handoff() {
  jq -e \
    --argjson clean_run "${clean_run}" \
    --argjson counter "${counter}" \
    --arg release "${GITHUB_SHA}" \
    --arg model_source "${MODEL_SOURCE_GIT_SHA}" \
    --arg job "${job_name}" \
    --arg output "${output_uri}" \
    --arg request_sha "sha256:$(sha256sum "${request_path}" | cut -d' ' -f1)" '
    .schema_version == "1.0.0" and
    .artifact_type == "heldout_processing_phase" and
    .clean_run == $clean_run and .test_access_counter == $counter and
    .release_git_sha == $release and .model_source_git_sha == $model_source and
    .processing_job_name == $job and .output_uri == $output and
    .request_sha256 == $request_sha' "${handoff_path}" >/dev/null
}

sanitize_description() {
  local description="$1"
  jq --arg region "${AWS_REGION}" --argjson clean_run "${clean_run}" '{
    schema_version: "1.0.0",
    artifact_type: "heldout_processing_job_evidence",
    processing_job_name: .ProcessingJobName,
    status: .ProcessingJobStatus,
    instance_type: .ProcessingResources.ClusterConfig.InstanceType,
    instance_count: .ProcessingResources.ClusterConfig.InstanceCount,
    creation_time: .CreationTime,
    end_time: .ProcessingEndTime,
    image_digest: (.AppSpecification.ImageUri | split("@") | .[-1]),
    region: $region,
    clean_run: $clean_run,
    exit_message_present: (.ExitMessage != null)
  }' "${description}" >"processing-job-evidence-clean-${clean_run}.json"
}

build_request

case "${mode}" in
  reserve-submit)
    reserve_counter
    if aws sagemaker describe-processing-job \
      --processing-job-name "${job_name}" >"existing-processing-job-clean-${clean_run}.json" \
      2>"existing-processing-job-clean-${clean_run}.error"; then
      validate_existing_job "existing-processing-job-clean-${clean_run}.json"
      verify_financial_snapshot
    elif grep -Eq 'ValidationException.*(Requested resource not found|Could not find)' \
      "existing-processing-job-clean-${clean_run}.error"; then
      verify_financial_snapshot
      aws sagemaker create-processing-job \
        --cli-input-json "file://${request_path}" >/dev/null
    else
      echo "held-out evaluation lookup failed" >&2
      exit 1
    fi
    write_handoff
    ;;
  poll)
    verify_handoff
    window_seconds="${POLL_WINDOW_SECONDS:-3000}"
    interval_seconds="${POLL_INTERVAL_SECONDS:-30}"
    [[ "${window_seconds}" =~ ^[1-9][0-9]*$ ]]
    [[ "${interval_seconds}" =~ ^[1-9][0-9]*$ ]]
    (( window_seconds <= 3000 ))
    (( interval_seconds <= 60 ))
    deadline="$((SECONDS + window_seconds))"
    while :; do
      aws sagemaker describe-processing-job \
        --processing-job-name "${job_name}" >"processing-job-description-clean-${clean_run}-private.json"
      validate_existing_job "processing-job-description-clean-${clean_run}-private.json"
      status="$(jq -er '.ProcessingJobStatus' "processing-job-description-clean-${clean_run}-private.json")"
      if [[ "${status}" == "Completed" ]]; then
        sanitize_description "processing-job-description-clean-${clean_run}-private.json"
        break
      fi
      if (( SECONDS >= deadline )); then
        break
      fi
      sleep "${interval_seconds}"
    done
    ;;
  collect)
    verify_handoff
    aws sagemaker describe-processing-job \
      --processing-job-name "${job_name}" >"processing-job-description-clean-${clean_run}-private.json"
    validate_existing_job "processing-job-description-clean-${clean_run}-private.json"
    status="$(jq -er '.ProcessingJobStatus' "processing-job-description-clean-${clean_run}-private.json")"
    if [[ "${status}" != "Completed" ]]; then
      echo "held-out evaluation did not complete within its bounded polling phases" >&2
      exit 1
    fi
    sanitize_description "processing-job-description-clean-${clean_run}-private.json"
    jq -e --arg image "${EVALUATION_IMAGE_URI##*@}" --arg hardware "${INSTANCE_TYPE}" '
      .status == "Completed" and .image_digest == $image and
      .instance_type == $hardware and .instance_count == 1 and
      (.creation_time | type == "string" and length > 0) and
      (.end_time | type == "string" and length > 0)' \
      "processing-job-evidence-clean-${clean_run}.json" >/dev/null
    sha256sum \
      "access-counter-clean-${clean_run}.json" \
      "output-uri-clean-${clean_run}.txt" \
      "${handoff_path}" \
      "${request_path}" \
      "processing-job-evidence-clean-${clean_run}.json" \
      >"processing-phase-checksums-clean-${clean_run}.txt"
    ;;
esac
