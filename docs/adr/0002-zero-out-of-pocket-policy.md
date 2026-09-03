# ADR 0002: Zero out-of-pocket policy

- Status: accepted by owner on 2026-09-02
- Supersedes: only the PRD’s permissive USD 10 owner-payment ceiling

## Context

The PRD permits at most USD 40 of planned pre-credit service usage and at most USD 10 charged to the owner’s payment method. The owner explicitly declined the USD 10 exposure.

## Decision

The maximum out-of-pocket amount is exactly USD 0, excluding tax treatment AWS may independently apply. The USD 40 campaign envelope and USD 40 required unused-credit reserve remain additional constraints, not spend targets.

A chargeable workflow may proceed only when all of these are true:

- Current regional upper-bound pricing has been retrieved or a conservative documented allowance is used for request-based services.
- Unexpired credit is visibly confirmed to apply to the exact service.
- Remaining applicable credit covers the new worst-case estimate, the conservative remaining plan, and the USD 40 reserve.
- Campaign spend plus the new estimate and remaining plan is no more than USD 40.
- The applicable job-hour cap and runtime cap remain satisfied.
- A protected GitHub environment grants the run-specific approval.
- A version-2 HMAC receipt binds the financial observation and protected reservation values to the exact
  workflow, commit, and complete dispatch inputs.
- The operation atomically reserves its maximum USD and CPU/GPU envelope in the conditional S3 campaign
  ledger before its first ordinary AWS mutation.

If applicable credit is missing, insufficient, expired, or uncertain, the workflow stops. It does not consume a payment-method contingency.

## Enforcement limits

The owner explicitly waived AWS Budget creation and email confirmation. Terraform retains dormant optional
actual/forecast budgets for a future explicit decision, but the waiver is not represented as a passed gate.
Public serving instead has a budget-independent automatic shutdown invocation within 24 hours; the shutdown
remains armed and recovery is manual.

AWS cost data can lag, conditional reservations are conservative commitments rather than billing locks, and
shutdown delivery/propagation is not instantaneous. The controls reduce exposure through one-job dispatch,
one instance, hard timeouts, cumulative fail-closed reservations, reserved concurrency, storage lifecycle,
and no idle compute. They cannot mathematically guarantee that AWS never assesses a charge. Every execution
therefore still requires a current console check by the owner or operator.

## Reconsideration

Only a new explicit owner decision may raise `maximum_out_of_pocket_usd`. Code currently validates that the value is exactly zero, so a policy change also requires a reviewed code change and ADR.
