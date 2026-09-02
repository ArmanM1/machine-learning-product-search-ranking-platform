# Model card: product reranking systems

Status: architecture and reporting contract; no trained candidate, promoted model, or quality improvement is claimed.

## Systems

### Diagnostic controls

- Input order preserves source candidate order.
- Seeded random uses a stable query-derived seed.

These validate the evaluator and are not competitive baselines.

### Competitive baselines

- BM25 over the current query’s supplied candidates, with tokenizer and `k1`/`b` pinned in configuration.
- Unchanged `cross-encoder/ms-marco-MiniLM-L6-v2`, exact revision `233902d25c440f23af6f7d6e94d2946bac0bee0a` in the current template. The exact-revision model API identifies Apache-2.0; `docs/license-review.md` records the review. Its weights are never updated.

### Candidate

The planned candidate fine-tunes the same cross-encoder architecture, isolating task-specific training from architecture choice. Initial configuration is a single relevance logit, `BinaryCrossEntropyLoss`, maximum length 256, learning rate `2e-5`, effective batch 32, at most three epochs, 10% warmup, validation nDCG@10 checkpoint selection, early stopping, seed 42, and deterministic final mode.

These are preregistered starting settings, not measured optima.

## Training data and sampling

Training targets use `project_graded_v1`. Difficult examples are lower-grade products that BM25 or the unchanged cross-encoder ranks above a higher-grade item for the same training query. Mining artifacts may contain training query IDs only. The default target mixture is 50% difficult and 50% stratified random examples, while preserving graded targets and reporting the realized mixture.

Mandatory validation-only ablations compare:

- stratified random sampling vs. mixed difficult/random sampling;
- title-only input vs. enriched product text.

## Intended use

- Offline comparison of reranking methods on supplied query-specific candidates.
- Curated public examples with known candidate IDs after data terms permit display.
- Small CPU inference behind a bounded portfolio API.

## Prohibited use and claims

- Full-catalog retrieval, personalization, purchasing, or safety-critical decisions.
- Claims of Amazon affiliation or an official competition score.
- Treating scores as calibrated probabilities.
- Claims of customer, revenue, conversion, production-scale, or multilingual impact.
- Claiming fine-tuning, AWS training, promotion, or improvement before corresponding run evidence exists.

## Evaluation contract

The primary metric is macro query-level project-defined graded nDCG@10. The primary release comparison is the frozen candidate minus the strongest unchanged baseline, with a paired 95% query bootstrap interval using 10,000 resamples. Promotion requires a positive point difference and a lower interval bound above zero, plus reproducibility and reporting gates.

## Runtime boundary

The public service accepts curated query IDs and up to 40 supplied candidates. The model and tokenizer are embedded in an immutable serving image. Warm and cold latency, memory, artifact size, architecture, Lambda memory, and model revision must be reported from measurements; all values are pending.

## Required trained-model fields

| Field | Value |
|---|---|
| Model ID/checksum | Pending |
| Base-model license review | Complete; Apache-2.0 metadata recorded in `docs/license-review.md` |
| Dataset/config/code hashes | Pending |
| Training hardware/image digest | Pending |
| Training duration/cost | Pending |
| Validation checkpoint decision | Pending |
| Mandatory ablation results | Pending |
| Two clean held-out reports, consecutive access counts, and bound report | Pending |
| Promotion decision | Pending |
| Known regressions | Pending |

## Limitations and risks

Cross-encoders scale linearly with candidate count and may cold-start slowly in Lambda. Source text and judgments can be incomplete. Ambiguous queries may have several defensible intents, while the pointwise loss does not directly optimize list order. Fine-tuning can amplify lexical or brand shortcuts. Failure slices and representative losses are required release artifacts, not optional notes.
