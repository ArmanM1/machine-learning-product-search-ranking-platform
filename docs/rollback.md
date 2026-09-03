# Release rollback

Status: procedure implemented in a manual workflow; no successful rollback is claimed until evidence is retained.

## Release invariant

Every production move records:

- release ID and model ID;
- evidence mode (`validation_only` or `verified`);
- release-manifest, typed public-evidence, and exact bundle-inventory SHA-256 values;
- serving image URI with digest;
- prior and new numeric Lambda versions;
- S3 version ID of `promoted/current.json`;
- immutable static release prefix;
- candidate and production readiness results.

ECR retains two `release-*` images, Lambda retains published versions, and S3 keeps versioned promotion pointers and immutable `releases/<release-id>/` site assets. Rollback does not retrain.

## Automatic non-promotion

If the held-out gate fails, `release.yml` still creates a checksummed, immutable outcome bundle at `promoted/releases/<report-id>/`. Its manifest and typed decision at `promoted/decisions/<report-id>.json` name the prior strongest baseline as the active model, while the public evidence names the evaluated candidate and records `release_status: failed`. Release does not mutate `promoted/current.json`. A later deployment may publish that negative result only after verifying the staged bundle and production state; it refreshes the API and site evidence while serving the same baseline model. The decision binds the prior pointer version for conflict detection and rollback.

## Deployment failure before durable activation

Candidate readiness and static staging do not write the live site root. On the first deployment, Terraform creates only the private Lambda/candidate surface until the cold-start and candidate API gates pass; a separate no-delete/no-replacement apply then creates public API and CloudFront resources without changing the gated runtime. If that first public publication or any later pre-activation step fails or is cancelled, final compensation sets Lambda reserved concurrency to zero. The same-origin staged browser check briefly moves `production` with the alias's captured revision ID, serves every static request from the immutable release prefix, and restores the prior alias before the step can succeed. If restoration cannot be proven, the workflow disables Lambda concurrency and final compensation retries the CAS restore; it never silently leaves the canary active. Diagnose using the candidate API/logs; do not weaken readiness checks.

## Deployment failure after alias movement

The workflow performs a second API and browser verification after activating the already-smoke-tested candidate. It compares every CloudFront-served static object with the local release build, exercises desktop/mobile/keyboard flows, and advances `promoted/current.json` only if production verification succeeds and the live pointer still matches the staged decision's bound prior version. Activation installs `EXIT`, `INT`, and `TERM` cleanup before its first mutation. On failure, cancellation, or timeout, revision-ID CAS restores the captured prior numeric Lambda version and the complete prior static release; if the pointer was already advanced, an ETag precondition restores the prior pointer bytes. The cleanup preserves the original process status. An unexpected alias or pointer revision is never overwritten and causes traffic to be disabled for operator recovery. The workflow then invalidates CloudFront and fails the run. This compensating rollback is retained as failure evidence; it does not turn a failed deployment into a successful release.

On the first baseline deployment there is no earlier healthy index or model revision. If its post-activation verification fails, the workflow removes the new root index and sets function reserved concurrency to zero. The next reviewed deployment reconciles the configured concurrency back to two. This is a safe shutdown, not a successful rollback claim.

## Manual rollback

Use the `rollback` action in `deploy.yml` with values copied from the last known-good deployment evidence:

- prior static `release_id`;
- prior healthy numeric Lambda version;
- prior S3 version ID of `promoted/current.json`;
- exact authorization phrase `ROLL BACK PUBLIC AWS DEMO`.

Before changing live state, the protected workflow validates the target deployment evidence and cross-binds its release, model, pointer version, Lambda version, exact resolved image URI/digest, and serving Git SHA to the requested rollback inputs and live immutable Lambda version. Separately, the pointer's release Git SHA must match the immutable release manifest; it need not equal the later serving-workflow SHA. The workflow inventories and downloads the complete immutable static target, installs `EXIT`, `INT`, and `TERM` compensation, moves the alias with its captured revision ID, restores the static release, compares both the CloudFront root and every public release object byte-for-byte, runs desktop/mobile/keyboard browser flows across the evidence pages, and checks `/healthz`, `/readyz`, rank, and comparison contracts. Only then does it advance `promoted/current.json` with an ETag precondition. An error, cancellation, or timeout through evidence publication triggers compensating restoration of the captured prior alias revision, complete static release, and pointer while preserving the original status; concurrent alias or pointer revisions are never overwritten, and incomplete restoration forces Lambda concurrency to zero.

## Kill-switch recovery is not rollback

The automatic public-cost shutdown sets ranker concurrency to zero and disables CloudFront. Neither a normal
Terraform reconciliation nor model rollback automatically restores those fields. After investigating the
trip, obtaining fresh financial authorization and a successful ledger reservation, the operator must
explicitly restore concurrency to two and re-enable the exact distribution before invoking a model rollback
or deployment. This is manual service recovery, not evidence that a release rollback succeeded.

## Verification

- [ ] `/healthz` returns the expected service revision.
- [ ] `/readyz` returns the expected prior model and data hash.
- [ ] A curated rank and comparison request matches the prior release fixtures.
- [ ] CloudFront serves byte-identical HTML, JavaScript, CSS, icons, and fixtures for the prior release, and the browser flow has no failed asset or API requests.
- [ ] `production` points to the recorded prior numeric Lambda version.
- [ ] `promoted/current.json` content matches the embedded model manifest.
- [ ] Rollback evidence is uploaded under `public/<release-id>/` with a checksum.
- [ ] Current cost and credits are rechecked.

If the rollback smoke test fails, stop public traffic by setting Lambda reserved concurrency to zero only under incident authorization, retain logs, and use the temporary human administrator path. Do not delete evidence during an incident.
