# AWS teardown

Status: safe procedure defined; teardown has not been executed or verified against live resources.

## Safety boundary

Teardown is destructive and requires exact environment selection plus owner authorization. Never run it against a workspace root, an unverified AWS account, or an unresolved backend. The production evidence and source-license requirements determine what must be exported first.

## Inventory

The disposable environment contains the resources listed in `docs/cloud-deployment.md`: two data/site buckets, three ECR repositories, IAM workload/OIDC roles, optional OIDC provider, Lambda and two aliases, two HTTP APIs, CloudFront/OAC/header policy, logs/alarms, optional SNS/EventBridge, and optional budgets. SageMaker jobs are run resources, not Terraform resources. The state bucket is a separate protected bootstrap environment.

## Pre-destroy capture

1. Stop new GitHub environment approvals and confirm no workflow is active.
2. Verify the AWS account, region `us-east-1`, Terraform workspace, backend bucket, and state key.
3. Confirm no SageMaker Training or Processing job is `InProgress`, `Starting`, or `Stopping` for the project prefix.
4. Export required final manifests, evaluation reports, cost evidence, deployment evidence, and rollback evidence to an approved local archive.
5. Record object checksums and confirm dataset/model redistribution terms before copying artifacts.
6. Decide whether the public demo should first display a retirement page.

## Ordered teardown

1. Disable or remove public entry points using a reviewed Terraform plan: CloudFront, HTTP APIs, Lambda aliases/function, and alarms.
2. Delete non-retained ECR images only after recording the promoted and rollback image digests.
3. Remove disposable S3 objects and every noncurrent version. Buckets use `force_destroy=false`, so Terraform refuses accidental deletion while data remains.
4. Review a full `terraform plan -destroy`; confirm every address belongs to the exact project/environment.
5. Run `terraform destroy` using temporary human credentials. GitHub CI is intentionally not granted broad identity teardown authority.
6. Remove the repository-specific OIDC role last. Delete the account-wide GitHub OIDC provider only if inventory proves no other repository uses it.
7. Retain the Terraform state bucket until all environment states and audit evidence have been archived and verified.

Versioned S3 buckets cannot be emptied by deleting only current objects. Use an audited version-aware tool, list every target key/version first, and verify the bucket name equals the Terraform output. Do not paste a generic recursive deletion command into another account.

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
- [ ] Budgets/SNS subscriptions are removed if no longer wanted.
- [ ] Billing and applicable-credit views are checked after AWS’s normal reporting delay.
- [ ] Sanitized teardown evidence records time, operator, account alias, region, plan hash, and residual resources.

Only after this checklist passes may `FR-CLOUD-009` be marked verified.
