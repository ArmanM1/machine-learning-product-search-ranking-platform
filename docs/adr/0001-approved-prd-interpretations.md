# ADR 0001: Approved PRD interpretations

- Status: accepted by owner on 2026-09-02
- Scope: experiment order, promotion, serving, rollback, and review

## Decision

The following interpretations resolve ambiguities without changing the PRD’s truth boundary:

1. The final SageMaker training run completes before the guarded held-out release for that frozen candidate. The release consists of two independent, consecutively counted Processing jobs followed by an offline checksum binder; neither source job selects a configuration.
2. If the candidate fails the preregistered release gate, the prior promoted baseline remains active and the negative result is retained unchanged.
3. FastAPI may co-serve the compiled frontend during local development. Production uses a private S3 origin through CloudFront and routes API traffic to API Gateway and Lambda.
4. A baseline service revision is deployed and verified first, creating the rollback target required before a candidate release.
5. External methodology or code review is best-effort. It may be claimed only if it actually occurs and retained evidence identifies the feedback and response.

The public interface should use a minimalist, chic visual direction: restrained color, generous spacing, precise typography, and evidence-first hierarchy. Visual polish may not obscure negative results, limitations, or provenance.

## Consequences

- Held-out evaluation cannot be used to decide training settings.
- A failed candidate is still a valid published experiment outcome.
- Production has one public CloudFront entry point while the candidate API remains an unlinked smoke-test surface.
- Rollback never requires retraining.
- No external-review badge, quote, or claim is a release prerequisite.

## Alternatives rejected

- Evaluating test after each training iteration: violates the locked-test policy.
- Promoting the newest candidate regardless of significance: violates the release gate.
- Serving the production SPA from FastAPI: loses the private S3/CloudFront architecture required by the PRD.
- Treating external review as completed by default: would invent evidence.
