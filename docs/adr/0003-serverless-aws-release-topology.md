# ADR 0003: Serverless AWS release topology

- Status: accepted, implemented, and publicly activated for the validation-only baseline

## Decision

Use private immutable images in ECR, optional run-to-completion SageMaker Training and Processing jobs for a future trained-candidate release, versioned S3 artifacts, Lambda container Function URLs, and a private S3 site origin behind CloudFront.

The serving image contains the active release model. Lambda receives CloudWatch logging permissions and sanitized `public/*` report reads only. It receives no raw-data permission. CloudFront sends `/api/*`, `/healthz`, and `/readyz` to the production Function URL and everything else to the private site bucket. A separate IAM-authenticated candidate Function URL supports pre-activation API checks.

The current release packages the pinned, unchanged cross-encoder in `validation_only` evidence mode. The immutable baseline bundle is published, and the private API, cold-start, 200-request warm, staged browser, durable CloudFront activation, production API, and independent browser checks completed successfully. No task-specific SageMaker Training or Processing evaluation has run.

## Why

This topology can produce managed-training evidence when the guarded candidate path is executed and already produces bounded serverless-serving evidence without always-on compute. Candidate and production Lambda aliases support smoke testing and rollback. S3 versioning preserves promotion-pointer history, and immutable release prefixes preserve the prior frontend.

## Alternatives considered

- SageMaker real-time endpoint: rejected because idle hourly cost conflicts with the cost boundary.
- ECS or Kubernetes: rejected as unnecessary operational scope.
- NAT Gateway plus private compute subnets: rejected because its idle cost is disproportionate for public-data, run-to-completion jobs.
- Public S3 website hosting: rejected because the origin must remain private.

## Known tradeoffs

- Container-image cold starts may be material and must be reported separately.
- The production Function URL remains directly addressable even though the user-facing entry point is CloudFront; application and Lambda resource policies enforce the intended route boundary.
- Reserved concurrency two intentionally throttles load tests above two concurrent executions; evidence must report the resulting 429s rather than imply higher scale.
