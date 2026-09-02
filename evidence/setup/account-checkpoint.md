# Account setup checkpoint

Status: partial owner report; do not add secrets or full cloud identifiers.

- Owner reported AWS ready in Chrome: yes, 2026-09-02.
- Selected region: `us-east-1`.
- Maximum out-of-pocket acceptance: no; effective maximum is USD 0.
- Repository requested: `ArmanM1/machine-learning-product-search-ranking-platform`, public. The owner portion was confirmed from the authenticated GitHub CLI; the repository did not yet exist at this checkpoint.
- Demo requested: public, generated CloudFront domain.
- License requested: MIT.
- Approved PRD interpretations: yes.

Verified without retaining private identifiers:

- The AWS console session was signed in and showed the no-charge plan.
- Applicable promotional credit was visible and had not expired at inspection time.
- The root user had zero access keys.
- AWS Budgets showed zero configured budgets.
- AWS CLI v2.36.36 is installed locally.
- The authenticated GitHub CLI reported the public owner name `ArmanM1`.

Explicit security deviation:

- The owner declined MFA on 2026-09-02. MFA was not configured or modified.
- Therefore `FR-SETUP-005` and the original Milestone 0 MFA acceptance criterion cannot pass.
- The observed compensating control is zero root access keys. Planned controls, not yet applied or verified, are no routine root use, repository-scoped OIDC for CI, and a temporary non-root human access path before any AWS write.

Still unresolved:

- Creation of the intended public repository and application/verification of its exact repository-bound OIDC trust.
- Temporary non-root CLI path verification; AWS CLI currently has no profile and STS is not authenticated.
- Redacted `aws sts get-caller-identity` success evidence.
- SageMaker CPU/GPU quota and service-access status.
- Budget thresholds approval (`yes` or `no`) and direct email confirmation (`yes` or `no`); no budgets currently exist.
- AWS risk decision: promotional credit cannot provide a hard USD 0 guarantee because applicability, tax, and billing lag are outside project control, so no AWS write is authorized under the current strict-USD-0 interpretation.
- Exact saved Terraform bootstrap plan and owner authorization.

Never add passwords, access keys, MFA data, recovery codes, cookies, payment details, or account numbers to this file.
