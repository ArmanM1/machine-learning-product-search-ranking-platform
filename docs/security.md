# Security

Status: design and policy configuration. The owner-approved MFA exception prevents strict PRD security conformance but is not an operational apply blocker. AWS apply remains blocked because temporary non-root CLI access, the cost-risk decision, budget choices, and an exact saved plan are unresolved.

## Protected assets

- AWS account and temporary human sessions.
- GitHub protected environments and OIDC trust.
- Raw/processed dataset, candidate checkpoints, and non-public reports.
- Promoted model pointer and immutable serving images.
- Held-out test access counter and final evaluation report.
- Public API availability and cost boundary.

## Trust boundaries and threats

| Threat | Control |
|---|---|
| Stolen long-lived cloud key | No CI access keys; GitHub exchanges OIDC tokens for short-lived role sessions |
| OIDC use from a fork or unreviewed branch | Trust `sub` must exactly match this repository and a named protected GitHub environment; audience is `sts.amazonaws.com` |
| Root-account misuse | The owner declined MFA as an accepted exception, so the PRD control is not satisfied. Zero root keys, no routine root use, temporary non-root access, and repository-scoped OIDC are the required compensating controls; the temporary path and OIDC binding remain pending. |
| Train/test leakage | Query-level split assertions, train-only miner, a training role with no `test.parquet` permission, manual held-out flag, and versioned access counter |
| Artifact substitution | Immutable paths/tags, SHA-256 manifests, S3 checksum verification, serving-image digest |
| Public bucket exposure | Account/bucket public-access blocks and CloudFront origin access control |
| Model reads raw data at runtime | Lambda role can read only `public/*`; model is embedded in the image |
| Arbitrary-code or SSRF input | Curated query IDs only; no uploads, URLs, paths, serialized objects, or shell input |
| Cost denial of service | API throttle, Lambda reserved concurrency two, zero provisioned concurrency, no always-on endpoint |
| Sensitive logging | Structured allowlist fields; no product descriptions, payloads, credentials, account IDs, or stack traces in public responses |
| Dependency compromise | Pinned locks, PR dependency scans, image scan, Terraform scan, non-root serving container requirement |

## Identities

### SageMaker training role

Reads a run-scoped staging prefix containing only `manifest.json`, `artifact-checksums.json`, `train.parquet`, and `validation.parquet`, plus base-model inputs and its versioned configuration. It has no `data/processed/*` or `test.parquet` permission. Writes only run checkpoint and metric prefixes. Pulls only the training repository.

### SageMaker processing role

Reads processed data, run artifacts, and promoted inputs. Writes run reports and sanitized public reports. Pulls only the evaluation repository.

### Lambda role

Writes its pre-created CloudWatch log group and reads `s3://<artifact-bucket>/public/*`. It has no raw-data or checkpoint access.

### GitHub workflow roles

Each protected environment has a separate role and trust policy bound to one exact `repo:<owner>/<repository>:environment:<name>` subject and the `sts.amazonaws.com` audience. The data role can read and create only the content-addressed prepared-data and sanitized data-preparation evidence prefixes; it cannot submit a job or change a release. The image role can push only project images. The training workflow role can read only the manifest/checksum index and train/validation source objects, stages those four allowed files under the run prefix, and can submit only training jobs. The baseline-release role can read only named validation-evidence files and create the initial promoted bundle/pointer; it cannot read processed objects or submit SageMaker jobs. The held-out role can submit only Processing jobs and advance counted release objects, and the production role can deploy the checksummed bundle. The infrastructure role reconciles project Terraform resources. Account-global cases required by AWS APIs are documented in the Terraform policy and remain protected by the exact environment reviewer gate.

### Human administrator

The normal target state uses an SSO or other temporary-credential path, reserves root for account-owner tasks, and enables root/account-owner MFA. The owner declined MFA on 2026-09-02 as an accepted exception, so strict PRD conformance is impossible and MFA will not be requested again. Infrastructure apply remains blocked until the temporary non-root CLI path and the other recorded cost, budget, and plan gates are resolved. No static key belongs in GitHub, local configuration committed to the repository, or chat.

## Public API rules

- Core routes accept known curated query IDs only.
- The unlinked candidate smoke API requires AWS IAM authorization; the production API is intentionally public and bounded.
- `top_k` is 1 through 40 and unknown fields are rejected where practical.
- Body/response limits are enforced in application validation within API Gateway’s platform limit.
- Errors include a request ID, stable code, and no stack trace or cloud identifier.
- `/readyz` succeeds only after model, curated assets, and release-manifest checksums pass.
- Benchmark labels are display annotations and never model inputs.

## Secret handling

The first release needs no application secret. GitHub repository variables hold non-secret resource identifiers. Notification email values should be stored as protected environment variables and are treated as sensitive Terraform inputs. If a future feature needs a secret, document the new threat and use Secrets Manager; do not overload environment variables or repository secrets without review.

## Verification checklist

- [x] Owner MFA decision recorded. MFA was declined as an accepted exception; strict PRD conformance remains unmet, and zero root access keys were observed.
- [ ] `aws sts get-caller-identity` succeeds via temporary credentials; public evidence is redacted.
- [ ] OIDC trust policy matches the exact public repository owner/name and protected environments.
- [ ] A fork pull request cannot obtain an AWS token.
- [ ] S3 public-access blocks and bucket policies are inspected after apply.
- [ ] Lambda effective policy contains no raw-data access.
- [ ] Reserved concurrency is two; no provisioned-concurrency configuration exists.
- [ ] Container executes as a non-root user and uses `trust_remote_code=False`.
- [ ] Dependency and image scans have no unreviewed high/critical findings.
- [ ] Public errors and logs pass redaction tests.
