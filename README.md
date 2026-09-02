# Machine Learning Product Search Ranking Platform

An implementation and evidence framework for a reproducible experiment that reranks supplied product candidates for ambiguous shopping queries.

> **Implementation status:** active build, not a completed PRD release. No quality, latency, cloud-execution, deployment, or cost result is claimed until its corresponding evidence gate passes.

The planned controlled experiment is designed to compare deterministic controls, BM25, an unchanged pretrained cross-encoder, and a task-fine-tuned cross-encoder on the US-English portion of Amazon's public Shopping Queries ESCI dataset. Its evidence contract covers query-level metrics, paired confidence intervals, ablations, failures, runtime, and artifact provenance. The scope is candidate reranking—not full-catalog retrieval or a live marketplace.

## Guardrails

- The official test set is inaccessible to normal local and CI commands.
- Raw data and model artifacts are not committed.
- Cloud jobs require an explicit current-price check and bounded authorization.
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
