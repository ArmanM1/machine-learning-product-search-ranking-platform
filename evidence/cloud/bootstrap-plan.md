# Bootstrap-plan evidence

- Plan status: configuration authored; exact AWS plan not generated or approved
- Region: `us-east-1`
- Maximum out of pocket: USD 0
- Campaign envelope: USD 40 before credits
- Required applicable-credit reserve: USD 40
- Terraform resource inventory: `docs/cloud-deployment.md`

## Still required before an AWS write

- [ ] Redacted account/plan identity recorded.
- [ ] Applicable-credit balance and expiration recorded privately.
- [x] Owner MFA decision recorded. The owner declined it on 2026-09-02 as an accepted exception; the PRD control remains unmet, but the exception is not itself an operational apply blocker.
- [ ] Temporary non-root access verified.
- [ ] Intended repository `ArmanM1/machine-learning-product-search-ranking-platform` exists and its exact owner/repository is inserted into OIDC trust.
- [ ] Existing GitHub OIDC provider state inspected.
- [ ] Budget yes/no and notification-email confirmation resolved.
- [ ] Owner accepts credits-only AWS risk despite the inability to hard-guarantee USD 0, or elects to keep the project undeployed.
- [ ] SageMaker quotas and live prices recorded.
- [ ] Saved Terraform plan generated and hashed.
- [ ] Owner explicitly authorizes that exact plan.

No box is implied complete by the presence of Terraform source.
