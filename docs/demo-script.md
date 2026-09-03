# Two-minute demo script

Status: narration template; bracketed fields must come from verified public evidence. If the candidate gate fails, use the negative-result variant.

## 0:00–0:15 — Shopper problem

“Short shopping queries can reward products that repeat the words without satisfying the likely intent. This platform reranks a supplied set of products; it is not a full marketplace search engine.”

Show the minimalist overview: one sentence, one verified outcome banner, and no decorative metric claims.

## 0:15–0:35 — Ambiguous query

Choose the first example produced by the documented selection procedure. Show the same candidate set under `[strongest unchanged baseline]` and `[promoted or evaluated candidate]`. State whether labels are benchmark annotations.

## 0:35–0:55 — Model change

“The candidate uses the same compact cross-encoder as the unchanged baseline, then fine-tunes it on graded Exact, Substitute, Complement, and Irrelevant judgments with a controlled mix of difficult and random training examples.”

Show the exact model revision, config hash, and mandatory ablations only if their artifacts exist.

## 0:55–1:15 — Representative win

Show a deterministically selected win, the rank movement, and the relevant text evidence. Use “consistent with” rather than claiming the shopper’s unobserved intent.

## 1:15–1:35 — Representative loss

Show a required loss or slice regression. Explain why the baseline was preferable and link to the failure report. Do not minimize the loss.

## 1:35–1:55 — Aggregate evidence

State only report-backed fields:

“On `[query count]` held-out query groups, the candidate changed project-defined graded nDCG@10 by `[delta]` versus `[baseline]`; the paired 95% interval was `[lower, upper]`. Warm p95 for 40 candidates was `[milliseconds]` on `[Lambda configuration]`, with cold starts reported separately.”

If the gate failed, say:

“The candidate did not clear the preregistered confidence gate. The prior baseline remains promoted, and the negative report, losses, and one validation-only next experiment are published.”

## 1:55–2:00 — Engineering boundary

Show the public provenance fields linking the semantic data hash, canonical split-manifest hash, code commit, container digest, cloud job, checkpoint, report, and release. End with: “It reranks supplied candidates; it does not retrieve an entire catalog or measure customer conversion.”

## Presenter checklist

- [ ] Demo URL is the generated CloudFront domain and has passed current smoke tests.
- [ ] Every spoken number resolves to a checksummed public report field.
- [ ] One win and one loss are visible without scrolling through hidden panels.
- [ ] Cold and warm latency are not conflated.
- [ ] AWS services named in narration have actual completed-workload evidence.
- [ ] No account ID, bucket path, signed URL, private product text, or internal stack trace appears.
- [ ] Visual presentation remains restrained and readable, but limitations and uncertainty are prominent.
