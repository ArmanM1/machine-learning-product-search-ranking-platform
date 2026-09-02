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

If held-out evaluation or any release gate fails, `release.yml` skips promotion. This is not a rollback: the prior model pointer and production service were never changed. Preserve the negative report.

## Deployment failure before alias movement

If candidate readiness or the staged CloudFront page fails, stop. The `production` alias and active root `index.html` remain unchanged. Diagnose using the candidate API/logs; do not weaken readiness checks.

## Deployment failure after alias movement

The workflow performs a second API and browser verification after activating the already-smoke-tested candidate. If this check fails, it automatically restores the captured prior numeric Lambda version, prior root `index.html`, and the prior `promoted/current.json` version recorded by the promotion pointer, then invalidates CloudFront and fails the run. This compensating rollback is retained as failure evidence; it does not turn a failed deployment into a successful release.

On the first baseline deployment there is no earlier healthy index or model revision. If its post-activation verification fails, the workflow removes the new root index and sets function reserved concurrency to zero. The next reviewed deployment reconciles the configured concurrency back to two. This is a safe shutdown, not a successful rollback claim.

## Manual rollback

Use the `rollback` action in `deploy.yml` with values copied from the last known-good deployment evidence:

- prior static `release_id`;
- prior healthy numeric Lambda version;
- prior S3 version ID of `promoted/current.json`;
- exact authorization phrase `ROLL BACK PUBLIC AWS DEMO`.

The protected workflow verifies that the Lambda version and S3 pointer version exist, restores the pointer, moves the production alias, restores the static release, invalidates CloudFront, and checks `/readyz`.

## Verification

- [ ] `/healthz` returns the expected service revision.
- [ ] `/readyz` returns the expected prior model and data hash.
- [ ] A curated rank and comparison request matches the prior release fixtures.
- [ ] CloudFront serves the prior release ID and no stale index.
- [ ] `production` points to the recorded prior numeric Lambda version.
- [ ] `promoted/current.json` content matches the embedded model manifest.
- [ ] Rollback evidence is uploaded under `public/<release-id>/` with a checksum.
- [ ] Current cost and credits are rechecked.

If the rollback smoke test fails, stop public traffic by setting Lambda reserved concurrency to zero only under incident authorization, retain logs, and use the temporary human administrator path. Do not delete evidence during an incident.
