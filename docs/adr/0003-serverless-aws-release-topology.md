# ADR 0003: Serverless AWS release topology

- Status: accepted design; deployment not yet evidenced

## Decision

Use private immutable images in ECR, run-to-completion SageMaker Training and Processing jobs, versioned S3 artifacts, a Lambda container behind API Gateway, and a private S3 site origin behind CloudFront.

The serving image contains the promoted model. Lambda receives CloudWatch logging permissions and sanitized `public/*` report reads only. It receives no raw-data permission. CloudFront sends `/api/*`, `/healthz`, and `/readyz` to the production HTTP API and everything else to the private site bucket.

## Why

This topology produces real managed-training and serverless-serving evidence while avoiding always-on compute. Candidate and production Lambda aliases support smoke testing and rollback. S3 versioning preserves promotion-pointer history, and immutable release prefixes preserve the prior frontend.

## Alternatives considered

- SageMaker real-time endpoint: rejected because idle hourly cost conflicts with the cost boundary.
- ECS or Kubernetes: rejected as unnecessary operational scope.
- NAT Gateway plus private compute subnets: rejected because its idle cost is disproportionate for public-data, run-to-completion jobs.
- Public S3 website hosting: rejected because the origin must remain private.

## Known tradeoffs

- Container-image cold starts may be material and must be reported separately.
- API Gateway remains directly addressable even though the user-facing entry point is CloudFront.
- Reserved concurrency two intentionally throttles load tests above two concurrent executions; evidence must report the resulting 429s rather than imply higher scale.
