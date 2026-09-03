# Account setup checkpoint

Status: partial owner report; do not add secrets or full cloud identifiers.

- Owner reported AWS ready in Chrome: yes, 2026-09-02.
- Selected region: `us-east-1`.
- Maximum out-of-pocket acceptance: no; effective maximum is USD 0.
- Credits-only AWS risk despite no hard USD 0 guarantee: authorized, 2026-09-02.
- Budget thresholds USD 1, 10, 25, and 40: approved; direct AWS email confirmation reported yes.
- Repository created: `ArmanM1/machine-learning-product-search-ranking-platform`, public. The owner portion was confirmed from the authenticated GitHub CLI and the initial commit was pushed on 2026-09-02.
- Demo requested: public, generated CloudFront domain.
- License requested: MIT.
- Approved PRD interpretations: yes.

Verified without retaining private identifiers:

- The AWS console session was signed in and showed the no-charge plan.
- Applicable promotional credit was visible and had not expired at inspection time.
- The authoritative credit view showed USD 100 remaining and USD 0 used at inspection time; the raw credit identifier is not retained.
- The root user had zero access keys.
- AWS Budgets showed zero configured budgets.
- AWS CLI v2.36.36 is installed locally.
- The authenticated GitHub CLI reported the public owner name `ArmanM1`.
- The GitHub OIDC provider and a temporary repository/environment-bound bootstrap role were created using short-lived account-owner authentication.
- The repository OIDC customization was independently read, changed from the default subject to GitHub's immutable numeric owner/repository subject, and read back with `use_immutable_subject=true` before any workflow assumption attempt.
- All seven cloud-write GitHub environments now exist, are restricted to `main`, and require the repository owner as reviewer; `main` is protected with linear history and force-push/deletion disabled.
- The temporary role's administrator attachment was removed before use and replaced with one inline policy limited to the deterministic encrypted Terraform-state bucket and lock objects.
- The last inspected sanitized spend and remaining-credit values are stored only as protected cost-gate secrets in all seven cloud-write GitHub environments; they must be refreshed from AWS before each cloud write.
- The `us-east-1` applied quotas for both approved SageMaker training instance types were `0` at inspection time. No-cost quota requests for `ml.m5.xlarge` and the frozen experiment's `ml.g4dn.xlarge` Spot Training quotas were recorded and advanced to open AWS service cases. AWS required each requested value to be `5` because its service-level default is `4`, while the project workflow remains hard-capped to one instance.
- The separate `ml.m5.xlarge for processing job usage` quota was also `0` at inspection time. AWS refused a third increase request while the two Spot requests remained open, so no Processing quota request was submitted. Held-out evaluation must remain fail-closed until that quota is applied at one or greater.

Explicit security deviation:

- The owner declined MFA on 2026-09-02. MFA was not configured or modified.
- Therefore `FR-SETUP-005` and the original Milestone 0 MFA acceptance criterion cannot pass.
- Compensating controls are zero root access keys, no routine root use, immutable repository-ID OIDC trust, and a least-privilege one-time bootstrap role. The first GitHub workflow run must still retain redacted proof that the non-root OIDC session succeeds.

Still unresolved:

- Redacted `aws sts get-caller-identity` success evidence from the non-root GitHub OIDC role.
- Exact provider-refresh permission preflight for the temporary state-bootstrap role, plus the externally controlled project boundary and one-time platform seed role.
- Approval of the pending SageMaker CPU and GPU Spot quota requests.
- An applied SageMaker Processing quota of at least one for `ml.m5.xlarge`; its increase request must be submitted after AWS permits another pending quota case.
- The exact approved budget-alert address as a protected GitHub environment secret; no budgets currently exist and no address will be guessed or written to this file.
- Exact saved Terraform bootstrap plan hash, reviewed source commit, and apply evidence.

Never add passwords, access keys, MFA data, recovery codes, cookies, payment details, or account numbers to this file.
