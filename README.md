# Machine Learning Product Search Ranking Platform

An implementation and evidence framework for a reproducible experiment that reranks supplied product candidates for ambiguous shopping queries.

> **Implementation status:** active build, not a completed PRD release. No quality, latency, cloud-execution, deployment, or cost result is claimed until its corresponding evidence gate passes.

The planned controlled experiment is designed to compare deterministic controls, BM25, an unchanged pretrained cross-encoder, and a task-fine-tuned cross-encoder on the US-English portion of Amazon's public Shopping Queries ESCI dataset. Its evidence contract covers query-level metrics, paired confidence intervals, ablations, failures, runtime, and artifact provenance. The scope is candidate reranking—not full-catalog retrieval or a live marketplace.

## Guardrails

- The official test set is inaccessible to normal local and CI commands.
- Raw data and model artifacts are not committed.
- Cloud writes require an operation-scoped, HMAC-bound financial snapshot and an atomic reservation in
  the private S3 campaign ledger before the first mutation. Pricing and service-specific limits remain
  separate fail-closed checks.
- GitHub OIDC roles are bound to one protected environment and one workflow file on `main`; baseline,
  trial-selection, benchmark, training, and deployment authority are not shared.
- The owner waived AWS Budget creation and email confirmation. Public serving therefore uses an automatic
  24-hour expiry and a least-privilege shutdown handler, but neither promotional credit nor these controls
  can provide a hard USD 0 billing guarantee.
- The AWS owner declined root MFA; this is recorded as a security deviation and prevents strict conformance with the original Milestone 0 acceptance criterion.
- No resume-ready result exists while this notice remains.

## Local development

```powershell
python -m uv sync --extra dev
python -m uv run pytest
python -m uv run search-rank --help
npm --prefix web install
npm --prefix web run dev
```

Full reproduction and verified results will be added only after the relevant milestone artifacts exist.
