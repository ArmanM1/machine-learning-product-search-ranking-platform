# AWS teardown

Status: a fail-closed disposable-dev workflow and exact external IAM contract are implemented; the
one-time external role bootstrap and live destroy have not been executed. Production teardown remains a
separate human-only procedure.

## Safety boundary

Teardown is destructive and requires exact environment selection plus owner authorization. Never run it against a workspace root, an unverified AWS account, or an unresolved backend. The production evidence and source-license requirements determine what must be exported first.

## Inventory

The disposable environment contains the resources listed in `docs/cloud-deployment.md`: two data/site
buckets, three ECR repositories, IAM workload/OIDC roles, optional OIDC provider, Lambda and two aliases,
two HTTP APIs, CloudFront/OAC/header policy, logs/alarms, and—when public serving exists—the shutdown Lambda,
dedicated role/log group, and recurring EventBridge expiry. The AWS Budget SNS trigger and budgets are
optional and remain disabled under the owner waiver. SageMaker jobs are run resources, not Terraform
resources. The state bucket and private campaign ledger are a separate protected bootstrap environment.

## Pre-destroy capture

1. Stop new GitHub environment approvals and confirm no workflow is active.
2. Verify the AWS account, region `us-east-1`, Terraform workspace, backend bucket, and state key.
3. Confirm no SageMaker Training or Processing job is `InProgress`, `Starting`, or `Stopping` for the project prefix.
4. Export required final manifests, evaluation reports, cost evidence, deployment evidence, and rollback evidence to an approved local archive.
5. Record object checksums and confirm dataset/model redistribution terms before copying artifacts.
6. Decide whether the public demo should first display a retirement page.

## Ordered teardown

1. Trip the public shutdown path and verify ranker concurrency is zero and CloudFront is disabled. Then remove
   public entry points using a reviewed Terraform plan: CloudFront, HTTP APIs, Lambda aliases/function,
   shutdown schedule/handler, and alarms.
2. Delete non-retained ECR images only after recording the promoted and rollback image digests.
3. Remove disposable S3 objects and every noncurrent version. Buckets use `force_destroy=false`, so Terraform refuses accidental deletion while data remains.
4. Review a full `terraform plan -destroy`; confirm every address belongs to the exact project/environment.
5. Run `terraform destroy` using temporary human credentials. GitHub CI is intentionally not granted broad identity teardown authority.
6. Remove the repository-specific OIDC role last. Delete the account-wide GitHub OIDC provider only if inventory proves no other repository uses it.
7. Retain the Terraform state bucket and its campaign ledger until all environment states and audit evidence
   have been archived and verified.

Versioned S3 buckets cannot be emptied by deleting only current objects. Use an audited version-aware tool, list every target key/version first, and verify the bucket name equals the Terraform output. Do not paste a generic recursive deletion command into another account.

## Automated disposable-dev proof

`.github/workflows/dev-teardown.yml` verifies the repository-side portion of `FR-CLOUD-009` without
granting GitHub production deletion authority. It is intentionally narrower than production teardown:

- the target is hard-coded to `dev` and `us-east-1`; there is no environment input;
- the protected `aws-dev-lifecycle` environment and one external OIDC role are bound to this workflow on
  `main` through the immutable repository owner/repository IDs;
- the role can mutate only deterministic dev state, buckets, repositories, base log groups, and the exact
  Terraform-managed dev roles; explicit denies cover named and tagged production resources;
- CloudFront, API Gateway, Lambda, SageMaker, the shared OIDC provider, and budgets are inventory-only.
  The workflow cannot delete those resources;
- the accepted fixture is exactly the 56-resource base dev platform with serving, budgets, notification
  email, and OIDC-provider creation disabled. Any missing, extra, drifted, deferred, non-AWS, replacement,
  or non-delete resource fails before bucket cleanup or apply;
- a plan run publishes only a value-free address/action manifest and its SHA-256. The separate destroy run
  must use the same full main commit, exact typed authorization phrase, and exact reproduced fingerprint;
- `scripts/empty_versioned_dev_bucket.py` validates the account-derived bucket name, deletes every object
  version and delete marker, aborts multipart uploads, and proves both inventories empty before Terraform
  apply;
- `scripts/empty_dev_repositories.py` targets only the three dev repositories, removes every image identity,
  and proves their image inventories empty before Terraform apply;
- post-destroy checks publish counts only. The evidence contains no account ID, ARN, bucket name, email,
  object key, job name, or workflow-run locator. The protected bootstrap state bucket is retained.

This constrained fixture is deliberate: untaggable CloudFront primitives need live resource IDs and would
otherwise require account-wide deletion authority. A dev state containing any serving or optional resource
is rejected and must use the human procedure above. Production is never an accepted automated target.

### One-time external bootstrap

The lifecycle role cannot be Terraform-managed because it must survive long enough to destroy the dev
state. From an authenticated human administrator session, create and protect the `aws-dev-lifecycle` GitHub
environment, then render the exact trust and inline policy. Use a private temporary directory and replace
only the placeholders locally:

```bash
python scripts/render_bootstrap_iam.py \
  --kind trust \
  --trust-purpose dev-lifecycle \
  --environment dev \
  --account-id "$AWS_ACCOUNT_ID" \
  --repository-owner "$GITHUB_OWNER" \
  --repository-owner-id "$GITHUB_OWNER_ID" \
  --repository-id "$GITHUB_REPOSITORY_ID" \
  --output "$PRIVATE_DIR/dev-lifecycle-trust.json"

python scripts/render_bootstrap_iam.py \
  --kind dev-lifecycle-policy \
  --environment dev \
  --account-id "$AWS_ACCOUNT_ID" \
  --repository-owner "$GITHUB_OWNER" \
  --repository-owner-id "$GITHUB_OWNER_ID" \
  --repository-id "$GITHUB_REPOSITORY_ID" \
  --output "$PRIVATE_DIR/dev-lifecycle-policy.json"

aws iam create-role \
  --role-name product-search-github-dev-lifecycle \
  --assume-role-policy-document "file://$PRIVATE_DIR/dev-lifecycle-trust.json" \
  --tags Key=Project,Value=product-search-ranking Key=Environment,Value=dev
aws iam put-role-policy \
  --role-name product-search-github-dev-lifecycle \
  --policy-name destroy-only-disposable-dev \
  --policy-document "file://$PRIVATE_DIR/dev-lifecycle-policy.json"
```

Store only its ARN as `AWS_DEV_LIFECYCLE_ROLE_ARN` in the protected environment. Also configure the same
non-secret Terraform repository/owner variables used by infrastructure workflows, the private state-bucket
variable, the dev OIDC-provider ARN, and the non-sensitive owner alias. Never upload the rendered documents
or private directory.

Provision the base dev fixture through the already documented temporary dev seed, delete that seed, and
dispatch `dev-teardown.yml` with `operation=plan`, the exact current full main SHA, and blank authorization
fields. Review the value-free manifest and record its SHA-256. Dispatch again at the same commit with
`operation=destroy`, that exact SHA-256, and `DESTROY DISPOSABLE DEV`.

The successful destroy artifact truthfully reports
`dev_resources_destroyed_external_role_cleanup_pending` and keeps `fr_cloud_009_complete=false`. From the
same human administrator session, remove the temporary external role last:

```bash
aws iam delete-role-policy \
  --role-name product-search-github-dev-lifecycle \
  --policy-name destroy-only-disposable-dev
aws iam delete-role --role-name product-search-github-dev-lifecycle
```

Delete the protected role variable and private temporary directory. Only after independent role-absence and
billing checks may the final portfolio evidence mark `FR-CLOUD-009` verified.

## State-bucket retirement

The bootstrap bucket has `prevent_destroy=true`. Retire it in a separate reviewed change only after:

- every environment is gone;
- state and lock objects are archived if required;
- the exact bucket name/account are independently verified;
- `prevent_destroy` is intentionally removed in version control;
- a final one-resource destroy plan is approved.

## Post-destroy verification

- [ ] Terraform reports no managed resources for the destroyed environment.
- [ ] No project SageMaker job or endpoint is running.
- [ ] No project Lambda, HTTP API, CloudFront distribution, ECR repository, or non-state S3 bucket remains.
- [ ] Project IAM roles are gone; shared OIDC provider decision is recorded.
- [ ] The public-expiry rule and shutdown handler are gone; optional budgets/SNS subscriptions are absent or
  removed if no longer wanted.
- [ ] Billing and applicable-credit views are checked after AWS’s normal reporting delay.
- [ ] Sanitized teardown evidence records time, operator, account alias, region, plan hash, and residual resources.

Only after this checklist passes may `FR-CLOUD-009` be marked verified.
