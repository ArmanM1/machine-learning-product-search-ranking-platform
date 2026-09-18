# Account setup checkpoint

Status: sanitized setup chronology. Current foundation claims are cross-checked against
[`evidence/status.json`](../status.json); secrets, exact billing values, and private cloud identifiers are
intentionally excluded.

- Owner reported AWS ready in Chrome: yes, 2026-09-02.
- Selected region: `us-east-1`.
- Maximum out-of-pocket acceptance: no; effective maximum is USD 0.
- Credits-only AWS risk despite no hard USD 0 guarantee: authorized, 2026-09-02.
- Budget thresholds USD 1, 10, 25, and 40 and direct email confirmation were initially reported as approved.
  Before infrastructure apply, the owner later waived AWS Budget creation and email confirmation so work
  could continue without that dependency. No AWS Budget object was created, and no address is retained here.
- Repository created: `ArmanM1/machine-learning-product-search-ranking-platform`, public. The owner portion was confirmed from the authenticated GitHub CLI and the initial commit was pushed on 2026-09-02.
- Demo requested: public, generated CloudFront domain.
- License requested: MIT.
- Approved PRD interpretations: yes.

Verified without retaining private identifiers:

- The AWS console session was signed in and showed the no-charge plan.
- Applicable promotional credit was visible and had not expired at inspection time.
- The authoritative credit view showed a positive, unexpired applicable-credit balance at inspection time.
  Exact remaining and used amounts, the credit identifier, and later billing observations are not retained in
  public evidence.
- The root user had zero access keys.
- AWS Budgets showed zero configured budgets at the initial inspection, consistent with the later waiver.
- AWS CLI v2.36.36 is installed locally.
- The authenticated GitHub CLI reported the public owner name `ArmanM1`.
- The GitHub OIDC provider and a temporary repository/environment-bound bootstrap role were created using short-lived account-owner authentication.
- The repository OIDC customization was independently read, changed from the default subject to GitHub's immutable numeric owner/repository subject, and read back with `use_immutable_subject=true` before any workflow assumption attempt.
- The cloud-write GitHub environments are restricted to `main` and require the repository owner as reviewer;
  `main` is protected with linear history and force-push/deletion disabled.
- The temporary role's administrator attachment was removed before use and replaced with one inline policy limited to the deterministic encrypted Terraform-state bucket and lock objects.
- Fresh spend and remaining-credit observations are stored only as protected, operation-bound cost-gate
  secrets in the relevant cloud-write environments; they must be refreshed from AWS before each write.
- Initial `us-east-1` inspection found zero applied capacity for the approved SageMaker Spot Training classes
  and for `ml.m5.xlarge` Processing. No-cost quota requests were opened in stages while every workflow
  remained hard-capped to one instance.
- Subsequent protected live probes confirmed capacity for the selected GPU Training and Processing classes.
  Each cost-bearing workflow still probes its exact quota immediately before use and fails closed if capacity
  is absent.
- Bootstrap and production Terraform are applied. The committed status records 57 managed resources and a
  clean post-apply plan, and successful protected image, data, infrastructure, and quota workflows exercised
  short-lived OIDC sessions without CI access keys.

Explicit security deviation:

- The owner declined MFA on 2026-09-02. MFA was not configured or modified.
- Therefore `FR-SETUP-005` and the original Milestone 0 MFA acceptance criterion cannot pass.
- Compensating controls are zero root access keys, no routine root use, immutable repository-ID OIDC trust,
  and least-privilege bootstrap/workload roles. Protected workflows subsequently exercised the non-root OIDC
  path successfully; that does not satisfy the missing MFA requirement.

Current public-evidence boundaries:

- `FR-SETUP-005` and strict Milestone 0 acceptance remain failed because MFA was declined.
- AWS Budgets and a budget-notification address remain intentionally absent under the later owner waiver.
- Exact financial observations, role/resource identifiers, plan hashes, and workflow-run locators remain in
  protected operational evidence rather than this public checkpoint.
- Every future AWS write still requires a fresh protected financial observation, an operation-bound receipt,
  and the workflow's live quota checks.

Never add passwords, access keys, MFA data, recovery codes, cookies, payment details, or account numbers to this file.
