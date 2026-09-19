# Two-minute demo script: validation-only portfolio release

Status: ready for the current unchanged cross-encoder release. Add the verified CloudFront URL and exact production latency only after the final deployment artifact and independent browser smoke test succeed.

## 0:00–0:20 — Rank a query

Open the **Rank** tab. Select a curated ambiguous shopping query and run it.

“This service reranks a supplied set of products. The action is the interface: choose a query, run the ranker, and inspect what moved. It is not a landing page and it does not retrieve an entire marketplace catalog.”

Point out the bounded candidate count and the clear loading/error state if the model is starting cold.

## 0:20–0:50 — Compare semantic and lexical ranking

Show the same candidates under the pinned cross-encoder and enriched-text BM25.

“The active model is the unchanged `cross-encoder/ms-marco-MiniLM-L6-v2` at an exact revision. It scores each query/product pair using enriched product text. BM25 is the lexical reference. No weights were fine-tuned by this project.”

Pick one visible rank movement and explain only what the displayed text supports. Use “consistent with the query” rather than asserting unobserved shopper intent.

## 0:50–1:20 — Show measured quality

Open the **Evidence** tab.

“On 2,057 validation query groups, the pinned cross-encoder reached 0.849037 graded nDCG@10 versus 0.821627 for enriched-text BM25, a descriptive difference of 0.027410. Exact MRR@10 was 0.819114 versus 0.741932, and exact top-1 rate was 0.721439 versus 0.610112.”

“Two separate scoring processes reproduced every quality metric, rank, and score exactly. These are validation results, not held-out test claims, and the official test split was not accessed.”

## 1:20–1:45 — Show production evidence

Show the release and operations sections in **Evidence**.

“The same release identity connects the model revision, data/configuration hashes, container, Lambda version, and public UI. Cold start is reported separately from the warmed request matrix.”

After final activation, read the warm p95 and cold observation directly from the live Evidence tab. Do not substitute numbers from an incomplete workflow run.

## 1:45–2:00 — State the boundary

“This release proves the complete baseline path: deterministic data, reproducible semantic ranking, immutable evidence, a bounded API, and a public interface. The repository also implements a guarded fine-tuning and held-out evaluation path, but that path has not run, so I do not claim a trained candidate or held-out improvement.”

End on the **Rank** tab with the result still visible.

## Presenter checklist

- [ ] The URL is the generated CloudFront domain and has passed an independent current smoke test.
- [ ] The interface shows live API data, not fixture mode.
- [ ] Every spoken quality value matches the committed validation evidence.
- [ ] Production latency values are read from the successful deployment artifact/live Evidence tab.
- [ ] Cold and warm latency are not conflated.
- [ ] No task-specific fine-tuning, held-out test result, promotion, rollback, or customer-impact claim is made.
- [ ] No account ID, bucket path, signed URL, private product text, or internal stack trace appears.
