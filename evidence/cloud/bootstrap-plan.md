# Historical bootstrap-plan evidence

Status: superseded by the applied, no-drift foundation recorded in
[`evidence/status.json`](../status.json). This file preserves the setup chronology without publishing account
identifiers, role/resource names, plan hashes, workflow-run locators, or financial balances.

- Region: `us-east-1`
- Maximum out of pocket: USD 0
- Campaign envelope: USD 40 before credits
- Required applicable-credit reserve: USD 40
- Terraform resource inventory and procedure: [`docs/cloud-deployment.md`](../../docs/cloud-deployment.md)

## Historical prerequisites and disposition

- [x] Applicable-credit availability and expiration were inspected privately. Exact values remain protected.
- [x] Owner authorized credits-only AWS work despite the acknowledged lack of a hard USD 0 guarantee.
- [x] Owner MFA decision was recorded. MFA was declined on 2026-09-02; `FR-SETUP-005` and strict
  Milestone 0 conformance remain unmet.
- [x] Temporary non-root access and the repository/environment/workflow-bound OIDC path were exercised by
  successful protected workflows without static CI access keys.
- [x] The public repository and protected environments were bound to immutable OIDC subject claims.
- [x] Existing OIDC provider state and repository subject customization were inspected and read back before
  workflow assumption.
- [x] Budget chronology was resolved: thresholds and email confirmation were reported early in setup, then
  the owner explicitly waived AWS Budget creation/email confirmation. No AWS Budget object exists.
- [x] Selected SageMaker Training and Processing quotas were probed live and confirmed usable; each workflow
  retains its fail-closed probe and one-instance cap.
- [x] Bootstrap and production Terraform were applied with protected authorization. The committed status
  records 57 managed resources and a clean post-apply plan.
- [x] The private campaign ledger was initialized and subsequent AWS writes remained subject to signed,
  operation-bound financial reservations.

The exact reviewed plan and apply records remain protected operational evidence. This sanitized historical
checkpoint does not create or change any model-training, evaluation, promotion, or public-deployment claim.
