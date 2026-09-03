# Cost controls

Status: controls are implemented in configuration and manual workflows; the private ledger, AWS resources,
spend, and credit balance are not claimed as applied or current until live evidence is retained.

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

`train.yml` and `release.yml` retrieve the current AWS Price List response for the selected `us-east-1`
instance. They use the highest matching hourly dimension as a conservative on-demand upper bound;
Managed Spot savings are never required for the gate to pass. Release cost is calculated for two
independent Processing jobs, each capped at two hours so both jobs and evidence binding fit the
hosted-runner boundary. Each workflow validates total runtime, campaign spend, applicable credit, reserve,
and a run-specific declared cap before calling SageMaker. The compact dispatch JSON documented in
`docs/workflow-inputs/README.md` remains part of the exact operation authorization, but it is not the
authoritative source for cumulative budget or hour state.

Every AWS-mutating workflow uses one version-2 protected snapshot. Its HMAC binds the exact UTC
observation time, fixed billing-console source, spend and applicable-credit strings, workflow name, full
commit, canonical digest of every dispatch input, and these protected reservation fields:

- campaign cap, required credit reserve, and maximum out-of-pocket amount;
- maximum USD reservation and remaining committed USD;
- CPU/GPU hours reserved by this operation; and
- authoritative CPU/GPU hours already used.

The maximum age is fixed at six hours. Sanitized preflight evidence publishes only timestamps, operation
and reservation digests, workflow/commit identity, the keyed receipt, and explicit redaction flags. It does
not publish balances, hour counters, reservation amounts, account identifiers, the HMAC key, or a billing
export. A receipt is valid for one exact workflow, commit, and input object; changing an authorization
phrase or any other input requires a new receipt.

After OIDC assumption and before the first ordinary AWS mutation, the workflow atomically reserves the
signed capacity in `cost-control/ledger.json` in the private Terraform-state bucket. Creation uses
`If-None-Match`; updates use the current S3 ETag with `If-Match`. The attached IAM policy permits only the
exact ledger object and requires those conditional headers, while all cost-bearing workflows also share
the `aws-financial-operations` concurrency group. The ledger sums prior reservations with the new maximum,
remaining commitment, authoritative spent amount, credit reserve, and CPU/GPU hours. A conflicting stale
write retries from the new ETag; an exact workflow/commit/input operation ID is idempotent. Reservations
are deliberately never released, so uncertainty can reject later safe work but cannot make later work look
cheaper. The one-time state-bucket bootstrap is the exception because the ledger cannot exist before its
bucket; it uses its separate USD 0.10 guard and initializes the empty ledger immediately after state
migration.

The snapshot and existing reservation are revalidated before later mutation boundaries. Missing,
future-dated, mismatched, malformed, expired, unreserved, or ledger-conflicting provenance fails closed.
Release repeats the check for the second independent Processing job rather than relying only on the first
check; the serving benchmark repeats it immediately before its fixed request matrix.

Before either held-out access counter is reserved, `release.yml` reads the exact regional SageMaker
quota `L-0307F515` (`ml.m5.xlarge for processing job usage`) and refuses access unless its finite applied
value is at least one. The sanitized result is validated against the strict
`SageMakerProcessingQuotaPreflight` contract, retained with the workflow artifact, and conditionally
published under the completed report's immutable public prefix. The initial live inspection found an
applied value of zero. AWS would not accept a third pending quota request while both Spot Training quota
requests remained open, so no Processing job may launch until this separate quota reaches at least one.

`prepare-data.yml` reserves the planning envelope's USD 1 S3 allowance before publishing the exact content-addressed data inventory. `baseline.yml` reserves a conservative USD 0.50 allowance for validation-only data transfer and runner evidence. Both remain manual, require current protected spend/credit values, keep `ALLOW_HELDOUT_EVAL=0`, and make no claim that an allowance is an actual charge.

The one-time `bootstrap-infrastructure.yml` workflow reserves a conservative USD 0.10 allowance for the
private S3 state bucket and requires at least that allowance above the USD 40 applicable-credit reserve.
It also requires the owner-approved maximum out-of-pocket value to remain exactly USD 0; the apply
authorization phrase explicitly acknowledges the separately accepted credits-only risk. Promotional
credits, billing lag, and taxes still cannot provide a hard external guarantee of USD 0.

Request-based serving does not have a meaningful fixed job price. The infrastructure and deploy workflows reserve a conservative USD 3 allowance for platform bootstrap and serving. The deployment protocol adds exactly one controlled candidate cold-start rank request and bounded CloudWatch log reads before the existing smoke and 200-request warm gate; it does not add provisioned concurrency. Before a public run, the operator must update the evidence with current S3, ECR, Lambda, API Gateway, CloudFront, CloudWatch, and transfer pricing.

The optional manual serving benchmark reserves an additional conservative USD 0.50 allowance and executes exactly 1,800 measured plus 90 warmup rank requests. It cannot run unless the same campaign, applicable-credit, reserve, and zero-out-of-pocket checks pass. Publishing latency percentiles also requires at least 199 successes in the 40-candidate/concurrency-one primary condition, at least 20 in every other measured condition, and at least one successful warmup per condition; failed attempts still consume request-based services and remain visible in the raw evidence.

## Passive controls

- The owner waived AWS Budget creation and email confirmation. `enable_budgets` therefore remains false and
  no budget email secret is required. The Terraform definitions remain dormant for a future explicit owner
  decision; if enabled later, actual and forecast budgets notify at USD 1, 10, 25, and 40, and the USD 10
  notification also invokes the dedicated shutdown path.
- Production public serving always creates a budget-independent EventBridge expiry. Its first invocation is
  within 24 hours and repeated invocations keep Lambda reserved concurrency at zero and disable the exact
  CloudFront distribution until explicit operator recovery. This is containment, not a real-time billing
  cutoff or hard USD 0 guarantee.
- S3 lifecycle for scratch data, run checkpoints, multipart uploads, and noncurrent versions.
- ECR immutable tags and count-bounded lifecycle rules.
- Seven-day retention on the exact project Lambda/API log groups. Account-shared SageMaker service groups are
  not mutated by the project identity; durable job evidence is exported to versioned S3.
- One SageMaker instance per manual job and a hard stopping condition.
- A quota increase never expands a job beyond that one-instance workflow cap. The initial account reported applied `ml.m5.xlarge` and `ml.g4dn.xlarge` Spot Training quotas of zero; AWS accepted only requests for `5` (its API minimum above the service default of `4`), and those requests themselves launch no compute and incur no usage charge.
- Held-out evaluation separately requires applied SageMaker Processing quota `L-0307F515` of at least one;
  the workflow checks it live and cannot reserve either access counter when capacity is absent. Each
  reservation is deterministic for its GitHub run and clean-job ordinal, so a rerun cannot consume a
  second counter value for the same intended access.
- Managed Spot Training with S3 checkpoints.
- No scheduled jobs or always-on model endpoint.

If the waived budgets are enabled by a later owner decision, they are account-wide rather than tag-filtered
so an unactivated or delayed cost-allocation tag cannot hide spend. Project resources still carry
`Project`, `Environment`, `Owner`, and `ManagedBy` tags for attribution. In a shared account, unrelated
spend can therefore trigger those conservative alerts.

## Operator check after every job

1. Record job status, billed seconds, actual or best-available cost, and the time the billing view was read.
2. Recheck the visible applicable-credit balance and expiration.
3. Account for billing lag conservatively.
4. Update cumulative CPU/GPU hours and campaign spend evidence.
5. Do not launch the next job if any value is unavailable or ambiguous.

The evidence template is `evidence/cloud/cost-evidence.template.json`. Never commit an AWS account number, payment details, or private billing export.
