# Model card: current validation-only reranker

Status: the current portfolio release serves a pinned, unchanged cross-encoder. Its validation quality and ranking output are reproducible; project-specific training and held-out evaluation have not been executed. Final public activation is pending.

## Current serving model

| Field | Value |
|---|---|
| Model | `cross-encoder/ms-marco-MiniLM-L6-v2` |
| Revision | `233902d25c440f23af6f7d6e94d2946bac0bee0a` |
| Input representation | Query paired with enriched product text |
| Weight updates by this project | None |
| Evidence mode | `validation_only` |
| Validation query groups | 2,057 |
| Official test accesses | 0 |
| Base-model license review | Complete; Apache-2.0 metadata recorded in `docs/license-review.md` |

The cross-encoder assigns a relevance score to each query/product pair, then sorts the supplied candidates by score. It does not retrieve products from an entire catalog.

## Reference systems

- Enriched-text BM25, with tokenizer and `k1`/`b` pinned in configuration, is the main lexical comparison.
- Title-only BM25 and title-only cross-encoder variants measure the effect of the input representation.
- Input order and seeded random are diagnostic controls, not competitive systems.

All systems receive identical query-specific candidate groups.

## Validation result

| Metric | Pinned cross-encoder | Enriched-text BM25 | Difference |
|---|---:|---:|---:|
| Project-defined graded nDCG@10 | 0.849037 | 0.821627 | +0.027410 |
| Exact MRR@10 | 0.819114 | 0.741932 | +0.077182 |
| Exact top-1 rate | 0.721439 | 0.610112 | +0.111327 |

Two separate scoring processes produced exact matches for all six recorded quality vectors, all ranks, and all scores. The complete values, query identity, hashes, and reproduction checks are in [`../evidence/baselines/milestone-2-validation.json`](../evidence/baselines/milestone-2-validation.json).

These comparisons are descriptive validation results. They do not establish held-out generalization, statistical significance, customer impact, or improvement from training by this project.

## Training status

No project-specific fine-tuning was used for this release. The repository contains an unexecuted, preregistered candidate path that would fine-tune the same architecture with graded Exact, Substitute, Complement, and Irrelevant judgments, difficult/random sampling, title/enriched-text ablations, frozen validation selection, and two clean held-out evaluations. Those controls remain useful engineering work, but they are not presented as completed experiments.

## Intended use

- Reranking a small, supplied set of product candidates for an English shopping query.
- Comparing semantic and lexical rankings for curated examples.
- Demonstrating reproducible ranking, evidence contracts, and bounded CPU inference in a portfolio application.

## Prohibited use and claims

- Full-catalog retrieval, personalization, purchasing, or safety-critical decisions.
- Claims of Amazon affiliation or an official competition score.
- Treating ranking scores as calibrated probabilities.
- Claims of customer, revenue, conversion, production-scale, or multilingual impact.
- Claims that this project fine-tuned, held-out-tested, or promoted a trained candidate.

## Evaluation boundary

The reported split is validation, not the official test split. Metrics are macro query-level values under the project’s documented ESCI relevance mapping. The cross-encoder/BM25 differences do not have a paired confidence interval and should not be described as a verified held-out gain. The guarded candidate-release contract requires a positive held-out point difference and lower paired-bootstrap bound above zero; that path has not run.

## Runtime boundary

The public service contract accepts curated query IDs and at most 40 supplied candidates. The model and tokenizer are embedded in an immutable Lambda container image. Deployment measures a newly published version’s cold request separately from the explicitly warmed request matrix.

The current deployment candidate completed its private API, cold-start, and 200-request warm gates, but the workflow has not yet produced a successful final activation artifact. Exact runtime numbers and the production URL will be added from that successful artifact rather than copied from an incomplete run.

## Reproducibility

- The model repository and exact revision are pinned.
- Data preparation uses deterministic query-level splits and content-addressed manifests.
- The baseline configuration, validation query set, quality matrix, ranks, and scores are checksum-bound.
- Two separate local processes reproduced all non-latency ranking fields exactly.
- Local timing was not reproducible across the two uncontrolled machines/runs, so those local latency values are not used as serving claims.
- The validation-only release bundle records zero test access and cannot contain trained-candidate provenance.

## Limitations and risks

Cross-encoders scale linearly with candidate count and can cold-start slowly on CPU. Source product text and relevance judgments can be incomplete. Short, ambiguous queries may support several defensible intents. The unchanged model was trained for general passage ranking, not specifically for this product corpus, and may overvalue lexical or brand cues. The current examples and aggregate metrics are validation-selected, and no user-behavior or business-outcome evidence exists.
