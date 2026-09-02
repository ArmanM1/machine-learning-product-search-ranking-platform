# Failure analysis

Status: analysis protocol and empty report scaffold; no examples or measured regressions are asserted.

## Required release contents

- Five representative wins.
- Five representative losses.
- Three ties or statistically/semantically uncertain changes.
- One query where lexical ranking is preferable.
- One Complement-versus-Exact confusion.
- Strongest improvement slice.
- Largest regression slice.
- Largest uncertain slice.
- Every predeclared slice below the minimum sample count.

## Selection procedure

1. Compute candidate-minus-strongest-baseline per-query primary-metric differences from the immutable report.
2. Sort deterministically by delta and query ID.
3. Draw from high, low, and near-zero delta bands using frozen thresholds.
4. Enforce diversity across query length, label composition, brand presence, text completeness, and lexical-overlap bins.
5. Apply dataset redistribution rules. If source terms prohibit public product text, retain private IDs/hashes and publish only permitted summaries.
6. Record the rule and rank position that selected each example; never replace an inconvenient example by hand without documenting the reason.

## Analysis template

For each example record:

- query ID/hash and permitted query text;
- candidate count and label composition;
- baseline and candidate ranked product IDs/titles as permitted;
- score, old/new rank, rank delta, and benchmark label;
- whether the model input used title-only or enriched text;
- short evidence-based interpretation;
- plausible alternative explanation;
- whether the case suggests a validation-only next experiment.

Do not infer intent as fact. Use language such as “consistent with” and distinguish model behavior from the ground-truth annotation.

## Slice table scaffold

| Slice | Frozen boundaries | Queries | Baseline nDCG@10 | Candidate nDCG@10 | Delta | 95% interval | Status |
|---|---|---:|---:|---:|---:|---|---|
| Query length | Pending freeze | Pending | Pending | Pending | Pending | Pending | Not evaluated |
| Label composition | Pending freeze | Pending | Pending | Pending | Pending | Pending | Not evaluated |
| Brand present | Pending freeze | Pending | Pending | Pending | Pending | Pending | Not evaluated |
| Text completeness | Pending freeze | Pending | Pending | Pending | Pending | Pending | Not evaluated |
| Lexical overlap | Pending freeze | Pending | Pending | Pending | Pending | Pending | Not evaluated |

## Root-cause taxonomy

- Lexical shortcut or query-term repetition.
- Brand dominance or missing-brand sensitivity.
- Truncation and long/noisy descriptions.
- Complement promoted above Exact.
- Substitute/Exact ambiguity.
- Sparse or conflicting annotations.
- Candidate-set composition/position artifacts.
- Domain mismatch from pretrained web-search data.
- Calibration/tie sensitivity that does not change ordinal quality.

## Next-experiment rule

If the primary gate fails, preserve the negative result and choose at most one justified iteration using validation data only. State the hypothesis, predicted slice effect, unchanged held-out boundary, added trial count, and cost. Do not change the split, gain mapping, primary metric, or slice definitions after seeing held-out results.
