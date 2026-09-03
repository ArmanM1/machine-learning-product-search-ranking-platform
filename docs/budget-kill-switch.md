# Production public-cost kill switch

Status: implemented in Terraform, handler code, and local tests; no live apply or trip is claimed.

## Owner waiver and automatic expiry

The owner explicitly waived AWS Budget creation and email confirmation. That waiver is recorded
as a deliberate PRD exception; it is never represented as a passed budget gate. Public production
serving therefore has a budget-independent, no-idle-compute expiry as its primary automatic safety
control. An exact EventBridge rule invokes the shutdown command no later than 24 hours after the
public resources are created. Both `ACTUAL` and `FORECASTED` AWS Budgets notifications at USD 10
remain available as an optional second trigger if budgets are enabled later.

Either trigger invokes a small Lambda command from the same immutable serving image.
The command first sets the public ranker function's reserved concurrency to zero and then disables
the uniquely tagged CloudFront distribution. Repeated delivery is safe: controls already at zero
or disabled are left unchanged, and every invocation emits a structured JSON result to its
seven-day log group.

The optional topic policy permits `sns:Publish` only from `budgets.amazonaws.com` for the owning
AWS account and the matching AWS Budgets source. Lambda invocation is bound independently to that one
topic and the exact scheduled EventBridge rule. The handler's
dedicated role can read and change concurrency only on the public ranker function and can read and
disable only the exact Terraform-created production distribution. The exact target identifiers are
passed privately as handler configuration; project tags remain attribution metadata rather than a dynamic
selection mechanism. It has no data-plane, training, artifact, or general infrastructure authority.

This is defense in depth, not a hard USD 0 guarantee or a real-time billing cutoff. The owner
authorized credits-only work despite that limitation. AWS cost data
and forecast evaluation can be delayed, SNS/Lambda delivery can be retried, and CloudFront disable
propagation is not instantaneous. Charges already incurred, in flight, delayed in reporting, or
outside the controlled public ranker can therefore appear after the USD 10 notification. The
manual credit, signed preflight, durable reservation, concurrency, and deployment controls remain
required; the waived AWS Budget/email steps remain visibly waived.

The kill switch never automatically restores service. The daily schedule continues to keep an
expired deployment fail-closed. Ordinary Terraform reconciliation ignores
external changes to the ranker's reserved concurrency and the distribution's enabled flag, so it
cannot silently undo a trip. Recovery requires an operator to investigate the budget event,
re-establish the approved financial evidence, explicitly restore ranker concurrency to two, and
explicitly enable the distribution. The `budget_kill_switch` Terraform output records whether the
control is armed, its trigger types and threshold, its topic and handler identities, and its exact
targets for release evidence.
