# Security

Status: implementation in progress. The owner-approved MFA exception prevents strict PRD security conformance but is not an operational apply blocker. The repository-bound OIDC provider and state-bootstrap role exist, but the live state policy and the GitHub/AWS workflow-bound OIDC subject migration remain pending. The external project boundary and platform seed role are not claimed as created; platform roles remain unverified until reviewed Terraform plans run. AWS Budgets and budget email confirmation were explicitly waived.

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
| OIDC use from a fork, rename-confusion repository, wrong workflow, or unreviewed branch | Trust requires the immutable owner/repository-ID subject, exact repository name and IDs, `refs/heads/main`, one named protected environment, one exact `workflow_ref`, and audience `sts.amazonaws.com` |
| Root-account misuse | The owner declined MFA as an accepted exception, so the PRD control is not satisfied. Zero root keys, no routine root use, short-lived console/CLI authentication, and repository-scoped OIDC are compensating controls. Root was used only to establish identity bootstrap; the temporary role's administrator policy was removed and replaced with a state-bucket-only inline policy before use. |
| Train/test leakage | Query-level split assertions, train-only miner, a training role with no `test.parquet` permission, manual held-out flag, and versioned access counter |
| Artifact substitution | Immutable paths/tags, SHA-256 manifests, S3 checksum verification, serving-image digest |
| Public bucket exposure | Account/bucket public-access blocks and CloudFront origin access control |
| Model reads raw data at runtime | Lambda role can read only `public/*`; model is embedded in the image |
| Arbitrary-code or SSRF input | Curated query IDs only; no uploads, URLs, paths, serialized objects, or shell input |
| Cost denial of service or concurrent budget oversubscription | Operation-bound HMAC receipt, conditional S3 campaign-ledger reservation, one shared financial concurrency group, API throttle, Lambda reserved concurrency two, zero provisioned concurrency, and automatic public-serving expiry within 24 hours |
| Sensitive logging | Structured allowlist fields; no product descriptions, payloads, credentials, account IDs, or stack traces in public responses |
| Dependency compromise | Pinned locks, PR dependency scans, image scan, Terraform scan, non-root serving container requirement |

All repository workflows and Terraform backends use HTTPS/TLS for S3, and every bucket enables public-access blocking and AES-256 SSE-S3. The fixed six-resource state bootstrap intentionally has no seventh bucket-policy resource, so it does not claim a resource-policy `aws:SecureTransport` deny; account-level preventive controls must supply that enforcement if required. The repository-scoped Trivy exception for `AVD-AWS-0132` is intentional: customer-managed KMS keys add recurring and request costs that conflict with the owner's USD 0 target, while the project stores public source data and non-secret model artifacts. Promotional credit, delayed billing, the reservation ledger, and automatic shutdown cannot make that target a hard guarantee. Revisit both exceptions before any sensitive data enters scope.

## Identities

### SageMaker training role

Reads a run-scoped staging prefix containing only `manifest.json`, `artifact-checksums.json`, `train.parquet`, and `validation.parquet`, plus base-model inputs and its versioned configuration. It has no `data/processed/*` or `test.parquet` permission. Writes only run checkpoint and metric prefixes. Pulls only the training repository.

The serving process verifies every file declared by the immutable release manifest before readiness can become true. Missing files, symbolic links, path escapes, or byte-checksum differences—including changes to curated queries or public evidence—keep `/readyz` unavailable. Its embedded web build is separately attested as API mode so the public API origin cannot expose fixture results.

### SageMaker processing role

Reads processed data, run artifacts, and promoted inputs. Writes only run-scoped reports; the held-out GitHub workflow separately validates and publishes the sanitized release evidence. Pulls only the evaluation repository.

### Lambda role

Writes its pre-created CloudWatch log group and reads `s3://<artifact-bucket>/public/*`. It has no raw-data or checkpoint access.

### GitHub workflow roles

Each protected environment has a separate role and trust policy bound to the immutable subject
`repo:<owner>@<owner-id>/<repository>@<repository-id>:environment:<name>:workflow_ref:<repository>/.github/workflows/<file>@refs/heads/main`, exact repository/ref claims, and the `sts.amazonaws.com` audience. The repository OIDC customization must enable immutable subjects with `repo`, `environment`, and then `workflow_ref`; the explicit `repo` key creates the immutable repository segment in a customized subject. Migration and readback are required before first use. `workflow_ref` is present for every workflow run, including these top-level workflows. The state-bootstrap and platform-seed trusts are separate generated documents for `bootstrap-infrastructure.yml` and `infrastructure.yml` respectively.

The data role can create only content-addressed prepared data and sanitized handoff evidence; it cannot submit a job or change a release. The image role can push only project images. The dedicated baseline role cannot submit SageMaker jobs. The training role can stage only its four named train/validation inputs and submit only training jobs. The trial-selection role can freeze only validation-selection evidence. Baseline-release can create the initial validation-only bundle/pointer; heldout-release alone can submit Processing jobs and advance counted release objects. Production can deploy, while production-benchmark has only its bounded read/request/evidence authority and cannot deploy or roll back. Infrastructure reconciles project Terraform resources. No baseline or benchmark authority is shared with training or production merely for convenience.

All ordinary AWS-mutating roles can read the exact private campaign ledger and can update only that object with an S3 conditional-write header. They cannot blind-overwrite it. Account-global cases required by AWS APIs are documented in the Terraform policy and remain protected by the exact environment/workflow reviewer gate.

### External identity handoff and permissions boundary

`scripts/render_bootstrap_iam.py` renders and validates the account-specific trust, state policy, external
permissions boundary, and one-time platform seed policy. The state role can create only the deterministic
state bucket, write only bootstrap state/lock objects, and simulate only its own effective policy. The
workflow requires all nine S3 provider refresh reads to simulate as allowed before the first create.

Separate dev and prod boundaries are externally created and intentionally absent from Terraform state. Every
Terraform-created role must carry its own environment's boundary. The boundary permits no role, trust,
inline-policy, or boundary mutation and explicitly denies artifact-bucket-policy mutation. The persistent
infrastructure role therefore reconciles services only. The production role has only production state/refresh
and bounded serving authority; its one bucket-policy grant targets the intentionally public static-site bucket,
while it has no artifact-bucket-policy access. Neither role can use a mutable proxy role or bucket policy to
reach held-out/private artifacts. Its serving, reconciliation, and conditional financial-ledger statements
are rendered into one inline policy whose complete minified document is tested and preconditioned below
AWS's 10,240-character role quota. Read-only identity refresh uses only the exact
product-search-ranking-prod-* role namespace plus the exact GitHub OIDC provider; the external boundary
enforces the same namespace and identity mutation remains absent. The
exact temporary environment seed can define only the deterministic project roles and base services; it has
no project-bucket-policy mutation at all. It may read only its own definition and the selected boundary for
live attestation, cannot modify either trust root, and is deleted immediately after handoff. The workflow binds
the seed mode and exact default-boundary hash
into the reviewed plan. Exact operator commands and recovery constraints are in `docs/cloud-deployment.md`.

The module pre-creates only the three project-named Lambda/API log groups with seven-day retention. It does
not create or mutate the account-shared `/aws/sagemaker/TrainingJobs` or `/aws/sagemaker/ProcessingJobs`
groups; job evidence is exported to the versioned artifact bucket, and any account-wide log retention must be
set by a separate administrator control rather than the project seed.

### Human administrator

The normal target state uses short-lived browser/CLI sessions and protected GitHub OIDC roles, reserving root for account-owner bootstrap and break-glass tasks. The owner declined MFA on 2026-09-02 as an accepted exception, so strict PRD conformance is impossible and MFA will not be requested again. No static key belongs in GitHub, local configuration committed to the repository, or chat. The state-bootstrap and environment seed roles are deleted after each exact handoff; the externally controlled environment boundaries remain.

## Public API rules

- Core routes accept known curated query IDs only.
- The unlinked candidate smoke API requires AWS IAM authorization; the production API is intentionally public and bounded.
- `top_k` is 1 through 40 and unknown fields are rejected where practical.
- Body/response limits are enforced in application validation within API Gateway’s platform limit.
- Errors include a request ID, stable code, and no stack trace or cloud identifier.
- `/readyz` succeeds only after model, curated assets, and release-manifest checksums pass.
- Benchmark labels are display annotations and never model inputs.

## Secret handling

The first release needs no application secret. GitHub repository variables hold non-secret resource identifiers. The owner waived AWS Budgets and email confirmation, so `AWS_BUDGET_NOTIFICATION_EMAIL` remains absent unless a later explicit decision enables budgets. The optional `AWS_ALARM_NOTIFICATION_EMAIL` is a protected environment secret and sensitive Terraform input. Neither address belongs in variables, logs, plans, or public evidence.

The financial observation time, spend, credit, reservation maximum/commitment, CPU/GPU reservation and usage counters, HMAC key, and receipt are protected environment secrets. The version-2 HMAC additionally binds the workflow, full commit, and canonical dispatch-input digest. None is a workflow input or public artifact. Before the first ordinary AWS mutation, the exact workflow/input/commit operation is conditionally reserved in the private S3 ledger. If a future application feature needs a secret, document the new threat and use Secrets Manager; do not overload repository secrets without review.

## Verification checklist

- [x] Owner MFA decision recorded. MFA was declined as an accepted exception; strict PRD conformance remains unmet, and zero root access keys were observed.
- [ ] `aws sts get-caller-identity` succeeds via temporary credentials; public evidence is redacted.
- [ ] Repository OIDC customization readback is immutable and includes `repo`, `environment`, then `workflow_ref`; every AWS trust matches one exact owner/repository identity, protected environment, workflow file, and `main`.
- [ ] A fork pull request cannot obtain an AWS token.
- [ ] S3 public-access blocks and bucket policies are inspected after apply.
- [ ] Lambda effective policy contains no raw-data access.
- [ ] Reserved concurrency is two; no provisioned-concurrency configuration exists.
- [ ] The private financial ledger denies unconditional writes, a stale ETag loses, and public serving expires within 24 hours; neither control is represented as a hard USD 0 guarantee.
- [x] Container source contracts require a non-root user and model loading uses `trust_remote_code=False`; deployed-image inspection remains part of cloud evidence.
- [ ] Dependency and image scans have no unreviewed high/critical findings.
- [x] Public errors and structured allowlist logs pass local redaction/field tests; CloudWatch evidence remains pending.
