# Evaluation methodology

Status: preregistered method; held-out results are intentionally absent until the guarded release.

## Ranking rule

For a query (q) and each supplied product (p_i), a system emits a real score (s(q,p_i)). Products sort by descending score, then ascending `product_id` for deterministic ties. Scores are ranking signals, not probabilities.

## Relevance mapping

Version `project_graded_v1` uses gains Exact 3, Substitute 2, Complement 1, and Irrelevant 0. This is a project definition.

## Primary metric

For rank (i),

```text
DCG@k = sum(i=1..k) gain_i / log2(i + 1)
nDCG@k = DCG@k / IDCG@k
```

`IDCG` sorts the same query’s supplied candidates by descending gain. Query nDCG is macro-averaged. Queries with `IDCG@k = 0` are excluded from the aggregate and counted separately. Primary `k = 10`; nDCG@5 is secondary.

## Secondary metrics

- Exact MRR@10: reciprocal rank of the first Exact item, or zero if absent in the first ten.
- Recall@10 for products graded Exact or Substitute.
- Pairwise ordinal accuracy over candidate pairs with unequal grades.
- Exact top-1 rate.

Every implementation has a hand-calculated fixture. Secondary metrics cannot replace the primary metric after held-out inspection.

## Compared systems

Input-order and seeded-random diagnostics, BM25, unchanged pretrained cross-encoder, and the frozen fine-tuned candidate all receive identical candidate groups. The strongest unchanged validation baseline is declared before test access. Baseline weights and parameters cannot change after that declaration.

## Paired uncertainty

- Resampling unit: query.
- Statistic: candidate-minus-baseline difference in macro metric.
- Method: paired nonparametric bootstrap, resampling query indices with replacement and preserving each system’s value for the same sampled query.
- Development: 2,000 resamples.
- Final: 10,000 resamples.
- Interval: percentile 95% interval.
- Seed: 42 unless a frozen versioned config says otherwise.

Report candidate and baseline estimates, difference, lower/upper bounds, included query count, degenerate/excluded count, resamples, seed, and confidence level.

## Primary promotion gate

Promotion is automatic from the immutable report only when:

1. Candidate held-out graded nDCG@10 exceeds the strongest unchanged baseline.
2. The lower paired 95% interval bound is greater than zero.
3. Mapping, query resampling, test-access count, query counts, exclusions, and baseline declaration match the frozen configuration.
4. Two clean final evaluations, executed in separate SageMaker Processing jobs and processes, agree within 0.002 absolute.
5. No required integrity, regression-disclosure, or artifact-checksum gate fails.

Otherwise the previous model remains promoted and the negative report is preserved. A single validation-only follow-up experiment may be justified without revisiting the held-out set.

## Predeclared slices

At least four slice dimensions must be frozen with exact bins before release: query token length, label composition, brand presence, text completeness, lexical overlap, and a reliable source/category field if supported. Every slice reports count, estimate, difference, and interval. The report calls out strongest improvement, largest regression, largest uncertain change, and insufficient sample sizes.

The default materiality threshold is an unexplained absolute nDCG@10 regression greater than 0.02 for a sufficiently populated slice; `slice_min_query_count` is currently 50.

## Example selection

Generate deterministic candidates for examples from per-query deltas, then apply documented diversity and redistribution constraints. Publish at least five wins, five losses, three ties/uncertain cases, one lexical-preferred case, and one Complement-vs-Exact confusion. Do not select only visually appealing wins.

## Performance protocol

Measure cold model load, first request, warm end-to-end, pure inference, serialization, peak resident memory, model size, training runtime, evaluation runtime, and estimated/actual cloud cost separately.

Warm Lambda tests use candidate counts 10, 20, and 40 and offered concurrency 1, 4, and 8, with at least 200 requests after warmup for the release latency claim. Report p50/p95/p99, successes, throttles/errors, sample count, Lambda memory, x86_64 architecture, `us-east-1`, reserved concurrency two, and model revision. Concurrency above two is expected to expose the configured bound; do not convert throttled offered load into a scale claim.

## Held-out guard

The test command requires all of the following:

- manual `release.yml` dispatch in the protected `heldout-release` environment;
- `ALLOW_HELDOUT_EVAL=1` in that workflow only;
- matching frozen configuration and candidate checkpoint SHA-256 values;
- processed-dataset identity (`DatasetManifest.processed_checksum`) and declared baseline IDs;
- an S3 object checksum match;
- a first test-access counter exactly one above the versioned prior value; the second clean job receives the immediately following value.

The counter increments separately before each Processing job accesses test data, so failed attempts remain counted. If the first clean job fails, the second is not opened. The binder accepts only two successful reports with consecutive counters and identical config, checkpoint, dataset, baseline, image, Git, and hardware identity. Pull-request and training workflows explicitly set the flag to zero.

Training is also separated at the cloud authorization layer: its workflow role may copy only `manifest.json`, `artifact-checksums.json`, `train.parquet`, and `validation.parquet` from the content-addressed dataset prefix. The SageMaker training role can read only that run-scoped four-file staging prefix and has no permission on `data/processed/*`. Consequently SageMaker input download cannot silently stage `test.parquet` before a counted release.

## Truthful reporting

Reports retain failures, exclusions, degenerate queries, trial count, negative slices, and example losses. No metric in a README, demo, or resume may be populated from this document; values must trace to a checksummed evaluation report.
