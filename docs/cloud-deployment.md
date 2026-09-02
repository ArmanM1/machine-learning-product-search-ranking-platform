# AWS cloud deployment

Status: locally validated configuration; no Terraform apply, AWS resource creation, SageMaker job, or public release is claimed. Apply is blocked by unresolved security, identity, budget, and authorization prerequisites.

## Prerequisite evidence

Do not run an apply until all fields below are recorded privately and the bounded plan is explicitly approved:

- AWS account identity and account plan.
- The recorded owner-approved MFA exception, zero root access keys, and a verified non-root temporary-credential path. MFA will not be configured or requested again.
- No root key and no long-lived GitHub key.
- `us-east-1` access for S3, ECR, IAM, Lambda, API Gateway, CloudFront, CloudWatch, Budgets, and SageMaker.
- Current SageMaker quota for one allowed instance.
- Current regional pricing and the applicable-credit balance/expiration.
- Exact public GitHub repository: `ArmanM1/machine-learning-product-search-ranking-platform`; OIDC binding remains pending.
- Budget thresholds and notification email approval/confirmation, or an explicit decision to leave budgets disabled.
- Separate authorization for a job, held-out access, and public deployment when each boundary is reached.

The owner’s current maximum out-of-pocket amount is USD 0. Promotional credit cannot hard-guarantee that boundary because applicability, tax, and billing lag are outside project control. No AWS write is authorized until the owner explicitly accepts credits-only AWS risk despite that limitation; otherwise the project remains local and undeployed.

## Bounded bootstrap plan

This is the exact resource inventory represented by Terraform. It is a proposal, not authorization and not evidence that the resources exist.

### State bootstrap

- One private, encrypted, versioned S3 Terraform-state bucket.
- Native S3 state locking; no DynamoDB table.
- `prevent_destroy` on the state bucket.

### Per environment

- One private, versioned artifact bucket.
- One private, versioned static-site bucket.
- Three private immutable ECR repositories: train, eval, serve.
- SageMaker training and processing IAM roles.
- Lambda execution IAM role.
- Seven repository-and-single-environment-bound GitHub OIDC workflow roles with distinct policies.
- Optionally, the account-wide GitHub OIDC provider if inspection confirms it does not already exist.
- Pre-created Lambda/API log groups with seven-day retention.
- Optionally, two cost budgets and an SNS/email path after email approval.
- Optionally, SageMaker failure EventBridge rules when an operations notification address is supplied.

### Serving resources, disabled by default

- One x86_64 Lambda container function with reserved concurrency two and no provisioned concurrency.
- `candidate` and `production` Lambda aliases.
- Two HTTP APIs: unlinked candidate smoke API and production API.
- One CloudFront distribution with a private S3 origin and production API origin.
- One CloudFront origin access control, one security-header policy, and one small SPA route-rewrite function.
- Model-load, server-error, and concurrency CloudWatch alarms.

Terraform never creates a SageMaker endpoint, notebook, schedule, NAT Gateway, load balancer, RDS database, or OpenSearch domain. SageMaker jobs are created only by the manual run workflows.

## Local review before approval

Copy examples; never edit or commit the example files with private values:

```powershell
Copy-Item infra/terraform/environments/bootstrap/terraform.tfvars.example infra/terraform/environments/bootstrap/terraform.tfvars
Copy-Item infra/terraform/environments/prod/terraform.tfvars.example infra/terraform/environments/prod/terraform.tfvars
```

The authenticated GitHub CLI identified the repository owner as `ArmanM1`, and the public repository now exists. Application and verification of the exact OIDC trust remain pending. Inspect whether the account already has `token.actions.githubusercontent.com`; duplicate creation will fail. Keep `enable_budgets=false` until the email decision is complete and `enable_serving=false` until public-deployment approval and an immutable serving digest exist.

Format and validate without an AWS backend:

```powershell
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform/environments/bootstrap init -backend=false
terraform -chdir=infra/terraform/environments/bootstrap validate
terraform -chdir=infra/terraform/environments/prod init -backend=false
terraform -chdir=infra/terraform/environments/prod validate
```

## Bootstrap sequence

The OIDC deployment role cannot create itself. Use the verified temporary human administrator session for the first two applies only.

1. Create and review a saved state-bootstrap plan.

   ```powershell
   terraform -chdir=infra/terraform/environments/bootstrap init
   terraform -chdir=infra/terraform/environments/bootstrap plan -out bootstrap.tfplan
   terraform -chdir=infra/terraform/environments/bootstrap show -no-color bootstrap.tfplan
   ```

2. After explicit approval of that exact one-bucket plan, apply the saved plan.

   ```powershell
   terraform -chdir=infra/terraform/environments/bootstrap apply bootstrap.tfplan
   ```

3. Copy `backend.hcl.example` to an ignored `backend.hcl`, replace only the state-bucket placeholder, and initialize production state.

   ```powershell
   terraform -chdir=infra/terraform/environments/prod init -backend-config=backend.hcl
   terraform -chdir=infra/terraform/environments/prod plan -out platform.tfplan
   terraform -chdir=infra/terraform/environments/prod show -no-color platform.tfplan
   ```

4. Review resource count, names, OIDC subjects, IAM policy, budgets state, tags, and the cost evidence. Obtain exact bootstrap authorization, then apply the saved plan.

5. Record Terraform outputs as protected GitHub environment variables. Do not store an AWS access key.

## GitHub environments

Create these protected environments with required reviewer approval:

| Environment | Workflow | Authority |
|---|---|---|
| `aws-infrastructure` | `infrastructure.yml` | Review/reconcile approved Terraform plan |
| `aws-images` | `build-images.yml` | Push immutable images |
| `aws-data` | `prepare-data.yml` | Publish one checksum-verified, content-addressed prepared dataset and sanitized handoff |
| `aws-training` | `baseline.yml`, `train.yml` | Run validation-only unchanged baselines or submit exactly one bounded training job; cannot read `test.parquet` |
| `baseline-release` | `bootstrap-baseline.yml` | Publish the validation-only baseline bundle and initial pointer; cannot read test data |
| `heldout-release` | `release.yml` | Increment two counters and run two clean held-out Processing jobs |
| `production` | `deploy.yml`, `benchmark-serving.yml` | Deploy/roll back the public service and run an explicitly authorized post-deployment performance matrix |

Required non-secret variables include:

```text
AWS_DEPLOY_ROLE_ARN  # different Terraform output ARN in each protected environment
AWS_ARTIFACT_BUCKET
AWS_SITE_BUCKET
AWS_TRAIN_ECR_REPOSITORY_URL
AWS_EVAL_ECR_REPOSITORY_URL
AWS_SERVE_ECR_REPOSITORY_URL
AWS_SAGEMAKER_TRAINING_ROLE_ARN
AWS_SAGEMAKER_PROCESSING_ROLE_ARN
AWS_TERRAFORM_STATE_BUCKET
AWS_GITHUB_OIDC_PROVIDER_ARN
TF_CREATE_GITHUB_OIDC_PROVIDER
AWS_LAMBDA_FUNCTION_NAME
AWS_CLOUDFRONT_DISTRIBUTION_ID
AWS_CLOUDFRONT_URL
TF_OWNER_ALIAS
```

Budget and alarm addresses, if approved, belong in the relevant protected environment. GitHub’s OIDC trust `sub` must match these environment names exactly. The `github_workflow_role_arns` Terraform output is a map keyed by environment; do not reuse the production ARN in another environment.

Current spend and remaining applicable credit belong in protected environment secrets named `AWS_CAMPAIGN_SPEND_TO_DATE_USD` and `AWS_REMAINING_APPLICABLE_CREDIT_USD`. Update them from the console before each cloud write. They are deliberately not dispatch inputs or public evidence fields.

## Workflow order

1. `pull-request.yml`: local tests, Terraform validation, builds, scans; never AWS writes or held-out access.
2. `infrastructure.yml`: manual plan/apply of an already approved resource inventory.
3. `build-images.yml`: manual immutable image push after ECR exists.
4. `prepare-data.yml`: manual, cost-gated preparation and immutable S3 publication under the semantic processed-dataset identity. Its dedicated role cannot submit SageMaker jobs or mutate release objects.
5. `baseline.yml`: manual unchanged-baseline scoring on validation only; downloads the manifest/checksum index and `validation.parquet`, never `test.parquet`, and emits the reviewed bootstrap handoff.
6. `train.yml`: manual cost-gated SageMaker Managed Spot Training; stages only the manifest/checksum index and train/validation Parquet objects into a run-scoped channel, and never receives or opens `test.parquet`.
7. `bootstrap-baseline.yml`: one-time, validation-only publication of the strongest unchanged baseline and create-if-absent pointer; never receives test-object permission.
8. `deploy.yml`: deploy and verify the baseline revision, creating the known-good rollback target.
9. `release.yml`: separate manual dispatch; two independent, consecutively counted held-out Processing jobs are checksum-bound before the automatic promotion gate.
10. `deploy.yml`: separate manual candidate deployment; candidate API and staged static release are tested before production alias movement, with post-activation verification and automatic compensating rollback.
11. `benchmark-serving.yml`: optional manual post-deployment evidence run over candidate counts 10/20/40 and offered concurrency 1/4/8, with 200 measured requests per condition. It reports throttles above the reserved bound and makes no throughput or scaling claim.

The baseline is the first public serving revision. Candidate deployment is allowed only after a valid promotion manifest exists.

`infrastructure.yml` deliberately separates review from apply. A plan run emits a redacted plan and canonical SHA-256. A later protected apply dispatch must provide that exact hash; any changed plan fails, and the workflow rejects delete or replacement actions. Destructive teardown remains a separately audited temporary-human procedure.

The baseline bundle carries typed `validation_only` public evidence with a zero test-access count. Candidate bundles carry typed `verified` evidence from the bound held-out report. Both modes are checksum-covered; neither is assembled with shell JSON projection.

## After every AWS action

- Capture sanitized outputs and SHA-256 hashes under the immutable run/release path.
- Confirm actual configuration against Terraform outputs.
- Inspect current billed usage and applicable credits, allowing for lag.
- Verify there is no unexpected running SageMaker job or endpoint.
- Stop before the next write if evidence is incomplete.

## Current unresolved prerequisites and owner inputs

- Application and verification of the exact `ArmanM1/machine-learning-product-search-ranking-platform` repository/environment OIDC subjects.
- Root/account-owner MFA remains declined as an accepted exception; the default PRD security gate therefore remains unmet, but this exception is not itself an operational apply blocker.
- Verified temporary non-root AWS CLI/STS access.
- Approved budget choice (`yes` or `no`) and, if yes, direct AWS email confirmation.
- Verified visible applicable-credit balance and expiration.
- Explicit decision to accept credits-only AWS work despite the inability to hard-guarantee USD 0, or to keep the project undeployed.
- Exact AWS bootstrap-plan authorization.
- Later job-specific, held-out, and public-deployment authorizations.
