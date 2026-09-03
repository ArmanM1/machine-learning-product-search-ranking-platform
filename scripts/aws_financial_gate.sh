#!/usr/bin/env bash
# Revalidate the protected financial snapshot immediately before AWS CLI mutations.
set -euo pipefail

: "${REAL_AWS_CLI:?REAL_AWS_CLI must name the unwrapped AWS CLI}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must name the checked-out repository}"
: "${TF_STATE_BUCKET:?TF_STATE_BUCKET must name the approved Terraform state bucket}"

requires_financial_gate=0
case "${1:-} ${2:-}" in
  "cloudfront create-invalidation" | \
  "ecr put-image" | \
  "lambda put-function-concurrency" | \
  "lambda update-alias" | \
  "s3 rm" | \
  "s3api delete-object" | \
  "s3api put-object" | \
  "s3api put-object-tagging" | \
  "sagemaker create-processing-job" | \
  "sagemaker create-training-job")
    requires_financial_gate=1
    ;;
  "s3 cp" | "s3 sync")
    if [[ "${4:-}" == s3://* ]]; then
      requires_financial_gate=1
    fi
    ;;
esac

if [[ "${requires_financial_gate}" -eq 1 ]]; then
  PYTHONPATH="${GITHUB_WORKSPACE}/src" \
    uv run --project "${GITHUB_WORKSPACE}" --frozen --no-dev python \
    "${GITHUB_WORKSPACE}/scripts/validate_financial_snapshot.py" emit --output /dev/null
  PYTHONPATH="${GITHUB_WORKSPACE}/src" \
    uv run --project "${GITHUB_WORKSPACE}" --frozen --no-dev python \
    "${GITHUB_WORKSPACE}/scripts/reserve_financial_capacity.py" verify \
      --bucket "${TF_STATE_BUCKET}" \
      --output /dev/null
fi

exec "${REAL_AWS_CLI}" "$@"
