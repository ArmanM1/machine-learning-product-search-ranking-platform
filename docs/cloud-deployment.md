# AWS cloud deployment

Status: locally validated configuration. The repository-bound OIDC provider and state-bootstrap role exist,
but the live state role still needs the generated complete refresh-read policy and both GitHub and AWS trust
must be migrated to the workflow-bound subject before first use. The external permissions boundary and
one-time platform seed role are not claimed as created. The owner waived AWS Budget/email setup. No
Terraform apply, campaign-ledger reservation, SageMaker job, model promotion, or public release is claimed.

## Prerequisite evidence

Do not run an apply until all fields below are recorded privately and the bounded plan is explicitly approved:

- AWS account identity and account plan.
- The recorded owner-approved MFA exception, zero root access keys, and a verified non-root temporary-credential path. MFA will not be configured or requested again.
- No root key and no long-lived GitHub key.
- `us-east-1` access for S3, ECR, IAM, Lambda, API Gateway, CloudFront, CloudWatch, Budgets, and SageMaker.
- Current SageMaker quota for one allowed instance: the selected Managed Spot Training quota before
  training and Processing quota `L-0307F515` before either held-out access counter.
- Current regional pricing and the applicable-credit balance/expiration.
- Exact public GitHub repository; its owner/repository database identifiers remain private inputs used only to
  generate immutable OIDC trust.
- The owner waived AWS Budget creation and email confirmation. Keep budgets disabled and the budget-email
  secret absent unless a later explicit owner decision reverses the waiver.
- Separate authorization for a job, held-out access, and public deployment when each boundary is reached.

The owner’s current maximum out-of-pocket amount is USD 0. Promotional credit, billing data, expiry, and
the public-serving shutdown path cannot hard-guarantee that boundary because applicability, tax, reporting
lag, delivery delay, and already-incurred requests are outside project control. The owner explicitly accepted
credits-only AWS work despite that limitation. Every workflow still fails closed unless its signed protected
state and atomic ledger reservation preserve the campaign and USD 40 credit reserve.

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
- Ten repository/environment/workflow-bound GitHub OIDC roles with distinct policies.
- Optionally, the account-wide GitHub OIDC provider if inspection confirms it does not already exist.
- Pre-created Lambda/API log groups with seven-day retention.
- A production public-serving shutdown handler and recurring 24-hour expiry when the public surface exists.
- Dormant optional actual/forecast budgets and their SNS trigger; these remain disabled under the owner waiver.
- Optionally, SageMaker failure EventBridge rules when an operations notification address is supplied.

### Serving resources, disabled by default

- `enable_serving=true` creates one x86_64 Lambda container function with reserved concurrency two and no provisioned concurrency, the `candidate` and `production` aliases, and an IAM-authenticated candidate smoke API.
- `enable_public_serving=true` additionally creates the unauthenticated production API and Lambda permission, the public-site bucket policy, and one CloudFront distribution with a private S3 origin and production API origin.
- The public flag is rejected unless `enable_serving=true`; it also creates one CloudFront origin access control, one security-header policy, and one small SPA route-rewrite function.
- Model-load, server-error, and concurrency CloudWatch alarms.

Terraform never creates a SageMaker endpoint, notebook, schedule, NAT Gateway, load balancer, RDS database, or OpenSearch domain. SageMaker jobs are created only by the manual run workflows.

## Local review before approval

Copy examples; never edit or commit the example files with private values:

```powershell
Copy-Item infra/terraform/environments/bootstrap/terraform.tfvars.example infra/terraform/environments/bootstrap/terraform.tfvars
Copy-Item infra/terraform/environments/prod/terraform.tfvars.example infra/terraform/environments/prod/terraform.tfvars
```

The public repository exists. Application and verification of the workflow-bound OIDC trust remain pending.
Inspect whether the account already has `token.actions.githubusercontent.com`; duplicate creation will fail.
Keep `enable_budgets=false` under the recorded waiver and both `enable_serving=false` and
`enable_public_serving=false` until public-deployment approval and an immutable serving digest exist.

Format and validate without an AWS backend:

```powershell
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform/environments/bootstrap init -backend=false
terraform -chdir=infra/terraform/environments/bootstrap validate
terraform -chdir=infra/terraform/environments/prod init -backend=false
terraform -chdir=infra/terraform/environments/prod validate
```

## Bootstrap sequence

The state bucket and Terraform-managed roles cannot safely create their own bootstrap identities. Use one
verified, temporary non-root human session for the external identity seed only. The repository contains a
deterministic generator that validates all five account-specific JSON documents without storing an account ID,
credential, or email address:

```powershell
$accountId = aws sts get-caller-identity --query Account --output text
$repository = gh repo view --json nameWithOwner --jq .nameWithOwner
$repositoryMetadata = gh api "repos/$repository" | ConvertFrom-Json
$repositoryOwner = $repositoryMetadata.owner.login
$repositoryOwnerId = [string]$repositoryMetadata.owner.id
$repositoryId = [string]$repositoryMetadata.id
$seedDir = Join-Path $env:TEMP "product-search-identity-bootstrap"
New-Item -ItemType Directory -Path $seedDir -Force | Out-Null
$common = @(
  "--account-id", $accountId,
  "--repository-owner", $repositoryOwner,
  "--repository-owner-id", $repositoryOwnerId,
  "--repository-id", $repositoryId,
  "--environment", "prod"
)
python scripts/render_bootstrap_iam.py --kind trust --trust-purpose state-bootstrap @common --output (Join-Path $seedDir "state-bootstrap-trust.json")
python scripts/render_bootstrap_iam.py --kind trust --trust-purpose platform-seed @common --output (Join-Path $seedDir "platform-seed-trust.json")
python scripts/render_bootstrap_iam.py --kind state-policy @common --output (Join-Path $seedDir "state-policy.json")
python scripts/render_bootstrap_iam.py --kind boundary @common --output (Join-Path $seedDir "boundary.json")
python scripts/render_bootstrap_iam.py --kind platform-seed-policy @common --output (Join-Path $seedDir "platform-seed-policy.json")
```

Keep the directory private and delete it after the handoff. The two trust documents are intentionally not
interchangeable. Both require audience `sts.amazonaws.com`, `main`, the exact repository and immutable
owner/repository IDs. The state-bootstrap document additionally requires environment `aws-state-bootstrap`
and `bootstrap-infrastructure.yml`; the platform-seed document instead requires environment
`aws-infrastructure` and `infrastructure.yml`.

### Workflow-bound OIDC subject migration

The existing repository OIDC subject template must be migrated in lockstep with the state role. Do not point
either trust document at the other workflow, and do not attempt to keep a permissive compatibility statement.
Use this fail-closed sequence while the verified human session remains available:

1. Create and protect the `aws-state-bootstrap` GitHub environment. Set its
   `AWS_BOOTSTRAP_ROLE_ARN` variable to the existing state role, set the immutable repository-ID variables,
   and add its protected state-bootstrap financial snapshot secrets. The workflow derives and verifies the
   deterministic state-bucket name after assuming the role; do not add a state-bucket variable here or reuse
   the `aws-infrastructure` environment.
2. Replace the existing state role's trust with `state-bootstrap-trust.json` and replace its inline policy
   with the generated complete state policy. Old-format GitHub tokens will now be rejected; this deliberate
   pause prevents a partially migrated workflow from receiving AWS authority.
3. Set the repository OIDC customization to immutable subjects with claim keys in exactly this order:
   `repo`, `environment`, then `workflow_ref`. The explicit `repo` key is required to place the immutable
   owner/repository-ID segment in the customized subject. Read the setting back and stop if any value differs.

```powershell
$oldInlinePolicies = @(
  aws iam list-role-policies --role-name product-search-github-bootstrap --query PolicyNames --output text
) -split "\s+" | Where-Object { $_ }
$oldInlinePolicies | ForEach-Object {
  aws iam delete-role-policy --role-name product-search-github-bootstrap --policy-name $_
}
aws iam update-assume-role-policy `
  --role-name product-search-github-bootstrap `
  --policy-document ("file://" + (Join-Path $seedDir "state-bootstrap-trust.json"))
aws iam put-role-policy `
  --role-name product-search-github-bootstrap `
  --policy-name fixed-six-resource-state-bootstrap `
  --policy-document ("file://" + (Join-Path $seedDir "state-policy.json"))

$oidcTemplate = @{
  use_default = $false
  use_immutable_subject = $true
  include_claim_keys = @("repo", "environment", "workflow_ref")
} | ConvertTo-Json -Compress
$oidcTemplate | gh api --method PUT "repos/$repository/actions/oidc/customization/sub" --input -
$oidcReadback = gh api "repos/$repository/actions/oidc/customization/sub" | ConvertFrom-Json
if ($oidcReadback.use_default -ne $false -or
    $oidcReadback.use_immutable_subject -ne $true -or
    (($oidcReadback.include_claim_keys -join ",") -ne "repo,environment,workflow_ref")) {
  throw "Repository OIDC subject customization does not match the required template"
}
```

The state policy is limited to the deterministic bucket, bootstrap state object, and exact `.tflock`. It
includes the nine AWS-provider refresh reads (`GetBucketPolicy`, ACL, CORS, website, accelerate,
request-payment, logging, replication, and object-lock configuration) and self-only
`iam:SimulatePrincipalPolicy` plus self-only reads needed to audit the role. The workflow first proves the live
role has exactly the generated trust, exactly one expected inline policy, and no attached policy, then
simulates every required action against the exact resources before any create. A missing read therefore fails
before a partial bucket can be stranded. The role has no bucket-delete permission.

1. From `main`, manually dispatch `bootstrap-infrastructure.yml` in the protected `aws-state-bootstrap`
   environment with `operation=plan` and a non-sensitive
   owner alias. The workflow assumes the bootstrap role through OIDC, proves it is an STS assumed-role
   identity, and creates a local-backend plan with Terraform 1.10.5 and the locked AWS provider.

2. Download and review the plan-run artifact. It contains only `reviewed-plan.txt`, with AWS account IDs,
   ARNs, email addresses, and access-key-shaped strings redacted, plus `reviewed-plan.sha256`. The saved
   binary plan, canonical private JSON, and local state never become artifacts. Record the full reviewed
   commit and canonical plan SHA-256 printed in the run summary.

   The canonical hash covers the reviewed commit, Terraform dependency-lock digest, CLI/provider selections,
   all managed-resource change objects, output changes, input variables, and plan-format/tool versions. It
   deliberately omits only the timestamp and read-only caller data whose STS session name changes on every run.

3. In a separate protected dispatch from `main`, select `operation=apply`, provide the same owner alias,
   reviewed commit, exact canonical hash, and the authorization phrase
   `APPLY APPROVED CREDITS ONLY STATE BOOTSTRAP`. The apply run checks out that reviewed commit only after
   proving it remains in `main` history, regenerates the local plan with the pinned toolchain, and refuses
   apply unless its canonical hash is identical. It rejects every delete, replacement, update, or resource
   outside the six-resource state-bucket inventory.

4. The workflow applies that newly generated saved plan and, in the same shell step, immediately migrates
   its local state to `s3://<state-bucket>/product-search-ranking/bootstrap/terraform.tfstate` with native
   S3 locking and encryption. It verifies the six remote resources, the encrypted state object, and a
   no-drift plan before the runner exits. A failure trap attempts to preserve any partial post-apply local
   state at that same encrypted key. If the bucket itself could not be created or the runner was forcibly
   terminated, do not dispatch again blindly: inventory the deterministic bucket and import any resources
   through a verified temporary non-root recovery session first.

5. From the temporary human session, create the external project boundary and the non-self-modifiable seed
   role. These are intentionally outside Terraform state. `create-policy` must fail if the deterministic
   boundary already exists; inspect the existing document rather than creating a new version blindly.

   ```powershell
   $boundaryArn = (aws iam create-policy `
     --policy-name product-search-ranking-prod-permissions-boundary `
     --policy-document ("file://" + (Join-Path $seedDir "boundary.json")) `
     --query Policy.Arn --output text)
   aws iam create-role `
     --role-name product-search-github-platform-seed-prod `
     --assume-role-policy-document ("file://" + (Join-Path $seedDir "platform-seed-trust.json"))
   aws iam put-role-policy `
     --role-name product-search-github-platform-seed-prod `
     --policy-name first-platform-apply-only `
     --policy-document ("file://" + (Join-Path $seedDir "platform-seed-policy.json"))
   ```

   The environment-specific managed boundary is below AWS's 6,144-character limit. Its resource-scoped
   service wildcards are a maximum-permissions ceiling, not grants; every inline identity policy remains
   action-specific. The boundary permits no role, trust, inline-policy, or boundary mutation and explicitly
   denies `PutBucketPolicy`/`DeleteBucketPolicy` on the artifact bucket, so a role-session principal cannot
   reach held-out or private artifacts through a bucket policy. The production deploy role may put only the
   exact static-site bucket policy needed by CloudFront; that bucket contains intentionally public assets and
   the role already owns its release-object writes. The temporary seed can audit but not modify itself or the
   boundary, and it has no artifact- or site-bucket-policy mutation. The three project-named Lambda/API log
   groups are exact seed resources; the account-shared SageMaker service log groups are intentionally outside
   this project identity's mutation scope.

6. Set the protected `aws-infrastructure` environment's `AWS_DEPLOY_ROLE_ARN` to the seed-role ARN. Also set
   `AWS_TERRAFORM_STATE_BUCKET`, `AWS_GITHUB_OIDC_PROVIDER_ARN`, `TF_OWNER_ALIAS`,
   `TF_GITHUB_REPOSITORY_OWNER_ID`, and `TF_GITHUB_REPOSITORY_ID`. Keep
   `TF_CREATE_GITHUB_OIDC_PROVIDER=false`. Copy `backend.hcl.example` to an ignored `backend.hcl`, replace only
   the state-bucket placeholder, and initialize production state for an optional local read-only check.

   ```powershell
   terraform -chdir=infra/terraform/environments/prod init -backend-config=backend.hcl
   terraform -chdir=infra/terraform/environments/prod plan -out platform.tfplan
   terraform -chdir=infra/terraform/environments/prod show -no-color platform.tfplan
   ```

7. Dispatch `infrastructure.yml` with `operation=plan`, `environment=prod`, `enable_budgets=false`, and
   `enable_serving=false`. Review resource count, role boundaries, immutable OIDC subjects, policies, tags,
   and cost evidence. Record the printed reviewed commit, production lockfile SHA-256, provider selections,
   deployment-identity mode, attested boundary SHA-256, and canonical plan SHA-256. Before either plan or
   apply, seed mode proves the exact seed ARN/trust, exactly one expected inline policy, no managed-policy
   attachments or seed boundary, and the exact generated default boundary document. In a separate protected
   dispatch, provide that exact commit and hash plus `APPLY APPROVED AWS BOOTSTRAP`. Apply fails if ancestry,
   identity mode, boundary, lockfile, providers, or regenerated plan differs.

8. After the first apply succeeds, repoint `AWS_DEPLOY_ROLE_ARN` in `aws-infrastructure` to
   `github_workflow_role_arns["aws-infrastructure"]` and in `production` to
   `github_workflow_role_arns["production"]`. Verify the boundary ARN equals
   `project_permissions_boundary_arn`. Then delete both temporary roles from the human session; retain the
   external boundary:

   ```powershell
   aws iam delete-role-policy --role-name product-search-github-platform-seed-prod --policy-name first-platform-apply-only
   aws iam delete-role --role-name product-search-github-platform-seed-prod
   aws iam delete-role-policy --role-name product-search-github-bootstrap --policy-name fixed-six-resource-state-bootstrap
   aws iam delete-role --role-name product-search-github-bootstrap
   ```

   Remove `AWS_BOOTSTRAP_ROLE_ARN` after deletion. The managed infrastructure role can reconcile project
   services but has zero role/trust/inline-policy mutation and zero project-bucket-policy mutation. Any plan
   that changes an OIDC provider, role, or inline role policy fails before apply unless the exact external seed
   is selected and attested; any bucket-policy change is rejected in this workflow in either identity mode.
   Recreate the seed for an intentional identity change and delete it again after the reviewed apply. The
   production role has the exact production state/refresh
   subset and bounded serving writes needed by `deploy.yml`, including the one public static-site bucket
   policy; it has no artifact-bucket-policy or identity mutation.

   `infrastructure.yml` does not accept a public-serving input and therefore cannot create the public surface for the first time. After backend initialization it inspects state and passes `enable_public_serving=true` only when a public API, CloudFront distribution, production Lambda permission, or site policy already exists. This preserves an existing public deployment during later reviewed reconciliations without bypassing the deployment gates.

   The disposable dev root uses a separate `product-search-ranking-dev-permissions-boundary`; never attach
   the production ceiling to dev roles. Generate `boundary` and `platform-seed-policy` again with
   `--environment dev` and create the deterministic `product-search-github-platform-seed-dev` only for a
   reviewed temporary dev apply. The dev and prod state keys, buckets, repositories, roles, and boundaries
   are disjoint.

9. Record the remaining Terraform outputs as protected GitHub environment variables. Do not store an AWS
   access key. Delete the temporary JSON directory after recording only sanitized hashes.

## GitHub environments

Create these protected environments with required reviewer approval:

| Environment | Workflow | Authority |
|---|---|---|
| `aws-state-bootstrap` | `bootstrap-infrastructure.yml` | External, one-time state role; create and migrate the six-resource backend only |
| `aws-infrastructure` | `infrastructure.yml` | Review/reconcile approved Terraform plans; use the temporary platform seed only for identity changes |
| `aws-images` | `build-images.yml` | Push immutable images |
| `aws-data` | `prepare-data.yml` | Publish one checksum-verified, content-addressed prepared dataset and sanitized handoff |
| `aws-baseline` | `baseline.yml` | Run validation-only unchanged baselines; cannot submit SageMaker jobs or read `test.parquet` |
| `aws-training` | `train.yml` | Submit exactly one bounded training job; cannot read `test.parquet` |
| `aws-trial-selection` | `freeze-trial-selection.yml` | Freeze one validation-only trial-selection manifest; cannot train, process, or deploy |
| `baseline-release` | `bootstrap-baseline.yml` | Publish the validation-only baseline bundle and initial pointer; cannot read test data |
| `heldout-release` | `release.yml` | Increment two counters and run two clean held-out Processing jobs |
| `production` | `deploy.yml` | Deploy or roll back the public service |
| `production-benchmark` | `benchmark-serving.yml` | Run one explicitly authorized post-deployment performance matrix; cannot deploy or roll back |

Required non-secret variables include:

```text
AWS_DEPLOY_ROLE_ARN  # environment-specific role in all ordinary environments except the three dedicated roles below
AWS_BOOTSTRAP_ROLE_ARN  # aws-state-bootstrap only; remove after the state handoff
AWS_BASELINE_ROLE_ARN  # aws-baseline only
AWS_TRIAL_SELECTION_ROLE_ARN  # aws-trial-selection only
AWS_BENCHMARK_ROLE_ARN  # production-benchmark only
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
TF_GITHUB_REPOSITORY_OWNER_ID  # immutable numeric GitHub owner database ID
TF_GITHUB_REPOSITORY_ID  # immutable numeric GitHub repository database ID
```

`AWS_BUDGET_NOTIFICATION_EMAIL` must remain absent while the owner waiver is active. If a later explicit
decision enables budgets, store the approved and confirmed address only in that protected secret. The optional
operational-alarm address belongs only in `AWS_ALARM_NOTIFICATION_EMAIL`. Never expose either address as a
repository variable or public artifact. GitHub's OIDC `sub` must match the exact environment, immutable
owner/repository IDs, and single workflow file on `main`. The `github_workflow_role_arns` Terraform output is
a map keyed by environment; never reuse one environment's role in another.

Except for the state bootstrap's documented pre-ledger exception, every AWS-mutating environment needs
`AWS_TERRAFORM_STATE_BUCKET` so it can reserve the exact operation in the private campaign ledger before its
first ordinary AWS write. Current spend, remaining applicable credit, and every protected reservation value
must be updated together from one AWS Billing and Cost Management console observation. Store them only in
protected environment secrets:

```text
AWS_CAMPAIGN_SPEND_TO_DATE_USD
AWS_REMAINING_APPLICABLE_CREDIT_USD
AWS_FINANCIAL_SNAPSHOT_OBSERVED_AT  # exact UTC RFC 3339 time, for example YYYY-MM-DDTHH:MM:SSZ
AWS_FINANCIAL_SNAPSHOT_HMAC_KEY  # 64 lowercase hex; protected, random, and never published
AWS_FINANCIAL_SNAPSHOT_RECEIPT_SHA256  # sha256:<64 lowercase hex> HMAC commitment
AWS_FINANCIAL_RESERVATION_MAX_USD
AWS_FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD
AWS_FINANCIAL_RESERVATION_CPU_HOURS
AWS_FINANCIAL_RESERVATION_GPU_HOURS
AWS_FINANCIAL_CPU_HOURS_USED_TO_DATE
AWS_FINANCIAL_GPU_HOURS_USED_TO_DATE
```

Generate the HMAC key once with a cryptographically secure 32-byte random generator and retain it only
as a protected environment secret. With the exact protected strings, workflow name, full commit, and
canonical `toJSON(inputs)` digest in the validator environment, run
`python scripts/validate_financial_snapshot.py receipt`; store only its `sha256:<hex>` output as
`AWS_FINANCIAL_SNAPSHOT_RECEIPT_SHA256`. Version 2 binds all of those values, including the authorization
input, so a receipt cannot be reused for another workflow, commit, or changed dispatch input. The workflow
recomputes it before every protected boundary and fails if any exact value differs. The public receipt is
safe against low-entropy balance guessing because the key is never written to repository evidence or Actions
artifacts. The source is fixed to `aws_billing_and_cost_management_console` and the TTL to six hours. No
private balance, reservation, hour counter, or HMAC key is accepted from workflow dispatch or written to
public evidence.

After OIDC assumption, `scripts/reserve_financial_capacity.py` creates
`cost-control/ledger.json` with S3 `If-None-Match` or updates the observed version with ETag `If-Match`. IAM
allows writes only to that object and only with the corresponding conditional header. A conflict rereads and
retries; the exact workflow/input-digest/commit operation ID is idempotent. The ledger sums all prior maximum
USD and CPU/GPU reservations against the campaign cap and reserve. Reservations are never released, which
can reject later safe work but cannot understate the committed envelope. All cost-bearing workflows also use
the shared `aws-financial-operations` concurrency group. State bootstrap cannot reserve before its bucket
exists, so it retains its separate USD 0.10 guard and initializes the empty ledger immediately after state
migration.

`train.yml`, `release.yml`, and `bootstrap-baseline.yml` keep the GitHub manual-dispatch surface
below its ten-input limit by accepting one strictly validated JSON configuration. Copy the relevant
template and follow the invocation guidance in
[`docs/workflow-inputs/README.md`](workflow-inputs/README.md). Missing, extra, duplicate,
non-string, malformed, or cross-inconsistent values fail before AWS credentials are configured.
The explicit authorization phrase remains a separate input; held-out release keeps its one-bit
access acknowledgement separate as well.

## Workflow order

1. `pull-request.yml`: local tests, Terraform validation, builds, scans; never AWS writes or held-out access.
2. `bootstrap-infrastructure.yml`: one-time, create-only exact-plan bootstrap and immediate local-to-S3 state migration.
3. `infrastructure.yml`: manual plan/apply of an already approved resource inventory.
4. `build-images.yml`: manual immutable image push after ECR exists.
5. `prepare-data.yml`: manual, cost-gated preparation and immutable S3 publication under the semantic processed-dataset identity. Its dedicated role cannot submit SageMaker jobs or mutate release objects.
6. `baseline.yml`: manual unchanged-baseline scoring on validation only; downloads the manifest/checksum index and `validation.parquet`, never `test.parquet`, and emits the reviewed bootstrap handoff.
7. `train.yml`: manual cost-gated SageMaker Managed Spot Training; stages only the manifest/checksum index and train/validation Parquet objects into a run-scoped channel, and never receives or opens `test.parquet`.
8. `freeze-trial-selection.yml`: manual validation-only freeze of the authorized final trial set under a
   dedicated role that cannot train, process held-out data, deploy, or publish a release.
9. `bootstrap-baseline.yml`: one-time, validation-only publication of the strongest unchanged baseline and create-if-absent pointer; never receives test-object permission.
10. `deploy.yml`: reconcile the baseline Lambda and IAM-authenticated candidate API privately; only after its controlled cold-start and candidate API gates pass, run a second no-delete/no-replacement plan that enables the first public API and CloudFront surface without changing the tested runtime, then verify the baseline revision and create the known-good rollback target.
11. `release.yml`: separate manual dispatch; it first proves that the exact `us-east-1`
    `ml.m5.xlarge for processing job usage` quota has finite applied capacity of at least one. Only then
    may it increment two consecutive access counters and run two independent held-out Processing jobs,
    which are checksum-bound before the automatic promotion gate. The sanitized quota receipt is retained
    in the Actions artifact and conditionally published under the completed report prefix. The workflow
    publishes an immutable deployment decision under `promoted/decisions/<release-id>.json` but does not
    mutate the live pointer.
12. `deploy.yml`: separate manual candidate deployment; Terraform state detection keeps an existing public surface enabled while a new private candidate version is reconciled. Before any smoke traffic, one first rank request against that newly published candidate version is correlated with its CloudWatch initialization report and structured model-load/memory logs, and the observed Lambda resolved-image URI must exactly equal the verified ECR repository-plus-digest URI. The workflow tests the candidate API, then maps staged browser static requests to the immutable release prefix without changing live-root objects. Its same-origin API check uses a brief revision-ID-CAS `production` canary that must restore the exact captured alias state or disable traffic. Durable activation verifies the exact CloudFront root, every release-object byte, and the complete desktop/mobile/keyboard browser/API flow, then may advance `promoted/current.json`. Activation and manual rollback compensate on normal errors, `INT`, `TERM`, and job cancellation; incomplete restoration forces Lambda concurrency to zero. The production alias revision and resolved image are re-observed immediately before deployment evidence advances a versioned canonical key with an ETag precondition, allowing a fresh-version retry while retaining every earlier S3 version.
13. `benchmark-serving.yml`: optional manual post-deployment evidence run over candidate counts 10/20/40 and offered concurrency 1/4/8, with 10 explicit warmups and 200 measured requests per condition. It checksum-binds the separate controlled cold observation, excludes it and pre-benchmark observations from all warm percentiles, reports throttles above the reserved bound, and makes no throughput or scaling claim.

The baseline is the first public serving revision. Candidate deployment is allowed only after a valid promotion manifest exists.

`bootstrap-infrastructure.yml` and `infrastructure.yml` deliberately separate review from apply. A plan run emits a redacted plan and canonical SHA-256. A later protected apply dispatch must provide that exact hash and reviewed commit; any changed source, production dependency lock, selected provider, or plan fails, and both workflows reject delete or replacement actions. The state-bootstrap workflow accepts create-only changes for exactly six resources. Destructive teardown remains a separately audited temporary-human procedure.

The baseline bundle carries typed `validation_only` public evidence with a zero test-access count. Candidate bundles carry typed `verified` evidence from the bound held-out report. Both modes are checksum-covered; neither is assembled with shell JSON projection.

### Immutable benchmark evidence

Immediately before benchmark publication, the workflow parses the cost preflight, live Lambda
configuration, standalone controlled-cold observation, performance report, validation receipt, and
checksum inventory through their exact strict Pydantic contracts. The validator also parses the
promotion pointer, release manifest, release checksum inventory, public evidence, and deployment
evidence. It requires one release, model, public run, dataset, model checksum, Lambda function and
version, controlled-cold observation, and versioned S3 source identity across the complete set.

The six benchmark JSON objects are published under
`public/<release-id>/performance/runs/<github-run-attempt-id>/sha256-<evidence-checksums-sha256>/`. Every
write uses conditional create. A retry may reuse an existing key only after downloading it and
proving byte identity; a different existing object fails closed. The workflow then downloads every
published object again, compares its bytes, checks the exact S3 object inventory, and repeats the
full typed and cross-artifact validation against the readback directory. There is no mutable
`latest` benchmark pointer and no blind overwrite path.

## After every AWS action

- Capture sanitized outputs and SHA-256 hashes under the immutable run/release path.
- Confirm actual configuration against Terraform outputs.
- Inspect current billed usage and applicable credits, allowing for lag.
- Verify there is no unexpected running SageMaker job or endpoint.
- Stop before the next write if evidence is incomplete.

## Current unresolved prerequisites and owner inputs

- Applied SageMaker Processing quota `L-0307F515` is currently zero. Submit its increase request as soon
  as AWS closes either pending Spot Training quota request, then retain a live applied-capacity receipt of
  at least one before held-out evaluation.
- Application and readback verification of the exact immutable repository/environment/workflow-bound OIDC
  subject template and the matching state-bootstrap trust.
- Root/account-owner MFA remains declined as an accepted exception; the default PRD security gate therefore remains unmet, but this exception is not itself an operational apply blocker.
- Verified temporary non-root AWS CLI/STS access.
- Verified visible applicable-credit balance and expiration.
- Exact AWS bootstrap-plan authorization.
- Later job-specific, held-out, and public-deployment authorizations.
