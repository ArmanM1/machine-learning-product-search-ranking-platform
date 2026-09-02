# Cost controls

Status: controls are implemented in configuration and manual workflows; no spend or credit balance is asserted.

## Binding limits

| Boundary | Limit |
|---|---:|
| Owner payment-method exposure | USD 0 |
| Planned pre-credit campaign envelope | USD 40 |
| Required remaining applicable-credit reserve | USD 40 |
| GPU allocation | 20 billed instance-hours total |
| Development or ablation GPU job | 4 hours maximum |
| Frozen final GPU job | 6 hours maximum |
| Paid CPU training and processing | 10 instance-hours total |
| Lambda reserved concurrency | 2 |
| Lambda provisioned concurrency | 0 |
| Post-release idle target | at most USD 2/month before credits |

These are simultaneous checks. Staying below one limit does not excuse breaching another.

The hosted GitHub training workflow uses a stricter five-hour final runtime plus a 30-minute Spot wait margin so evidence capture can finish inside GitHub’s six-hour job limit. The PRD’s six-hour ceiling remains an absolute maximum, not a requested duration.

## Planning envelope

| Area | Maximum planning allowance |
|---|---:|
| SageMaker GPU training | USD 20 |
| SageMaker CPU and processing | USD 4 |
| S3 | USD 1 |
| ECR | USD 1 |
| Lambda, API Gateway, CloudFront | USD 1 |
| CloudWatch and transfer | USD 3 |
| Unclassified price drift reserve | USD 10 |
| Total | USD 40 |

The values are caps from the PRD, not current prices or expected invoices.

## Workflow guard

`train.yml` and `release.yml` retrieve the current AWS Price List response for the selected `us-east-1` instance. They use the highest matching hourly dimension as a conservative on-demand upper bound; Managed Spot savings are never required for the gate to pass. Release cost is calculated for two independent Processing jobs, each capped at two hours so both jobs and evidence binding fit the hosted-runner boundary. Each workflow validates total runtime, accumulated CPU/GPU hours, campaign spend, applicable credit, reserve, and a run-specific declared cap before calling SageMaker.

`prepare-data.yml` reserves the planning envelope's USD 1 S3 allowance before publishing the exact content-addressed data inventory. `baseline.yml` reserves a conservative USD 0.50 allowance for validation-only data transfer and runner evidence. Both remain manual, require current protected spend/credit values, keep `ALLOW_HELDOUT_EVAL=0`, and make no claim that an allowance is an actual charge.

Request-based serving does not have a meaningful fixed job price. The infrastructure and deploy workflows reserve a conservative USD 3 allowance for bootstrap and serving. Before a public run, the operator must update the evidence with current S3, ECR, Lambda, API Gateway, CloudFront, CloudWatch, and transfer pricing.

The optional manual serving benchmark reserves an additional conservative USD 0.50 allowance and executes 1,800 measured plus 90 warmup rank requests. It cannot run unless the same campaign, applicable-credit, reserve, and zero-out-of-pocket checks pass.

## Passive controls

- Two AWS Budgets, one actual and one forecast, each with USD 1, 10, 25, and 40 thresholds. They are disabled until the owner approves and confirms the email address.
- S3 lifecycle for scratch data, run checkpoints, multipart uploads, and noncurrent versions.
- ECR immutable tags and count-bounded lifecycle rules.
- Seven-day CloudWatch log retention.
- One SageMaker instance per manual job and a hard stopping condition.
- Managed Spot Training with S3 checkpoints.
- No scheduled jobs or always-on model endpoint.

The budgets are account-wide rather than tag-filtered so an unactivated or delayed cost-allocation tag cannot hide spend. Project resources still carry `Project`, `Environment`, `Owner`, and `ManagedBy` tags for attribution. In a shared account, unrelated spend can therefore trigger these conservative alerts.

## Operator check after every job

1. Record job status, billed seconds, actual or best-available cost, and the time the billing view was read.
2. Recheck the visible applicable-credit balance and expiration.
3. Account for billing lag conservatively.
4. Update cumulative CPU/GPU hours and campaign spend evidence.
5. Do not launch the next job if any value is unavailable or ambiguous.

The evidence template is `evidence/cloud/cost-evidence.template.json`. Never commit an AWS account number, payment details, or private billing export.
