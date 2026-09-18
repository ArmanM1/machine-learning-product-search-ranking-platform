# ADR 0005: Promotion CLI evidence boundary

- Status: accepted
- Scope: local promotion command and immutable release assembly

## Context

The PRD lists `python -m search_rank.cli promote --report-id <report-id>` as the abbreviated
stable command. A report ID alone cannot prove which validation-selected training execution
produced the candidate, whether the candidate bytes are unchanged, or which runtime and cost
observations belong to the two clean held-out evaluations. Inferring those values from a mutable
directory would make the release depend on ambient state.

## Decision

Keep the `promote` command name and `--report-id` entry point, but require every independent
release input at the command boundary. The exact command used by `release.yml` is:

```bash
uv run python -m search_rank.cli promote \
  --report-id "$(pwd)/.release/evaluation/evaluation-report.json" \
  --trial-selection "$(pwd)/trial-selection.json" \
  --selected-training-run-manifest \
    "$(pwd)/.trial-selection-manifests/candidate_treatment.json" \
  --selected-training-model-artifact \
    "$(pwd)/.release/training-model-artifact.json" \
  --evaluation-runtime-seconds "${evaluation_runtime_seconds}" \
  --evaluation-estimated-cost-usd "${evaluation_estimated_cost_usd}"
```

`evaluation_runtime_seconds` is the sum of the two verified SageMaker Processing wall-clock
intervals. `evaluation_estimated_cost_usd` comes from the checksummed release cost preflight.
Add `--evaluation-actual-cost-usd "${evaluation_actual_cost_usd}"` only after that charge has
been reconciled; omission truthfully records that the actual charge is not yet known.

The CLI checksum-verifies the report against its completed command summary, the trial selection
against the selected training `RunManifest`, and the source `ModelArtifact` against the selected
checkpoint. It also keeps training runtime/cost separate from evaluation runtime/cost in public
provenance. These required arguments are a fail-closed refinement of the PRD shorthand, not a
second promotion path.

## Consequences

- A copied report or mutable “latest” directory cannot silently choose a training artifact.
- Promotion callers must stage the exact immutable inputs before invoking the command.
- Local reproduction uses the same interface as the protected release workflow.
- The concise PRD example remains useful as a command index, but it is not an executable release
  authorization by itself.

## Alternatives rejected

- Discover the latest training artifacts automatically: ambiguous and retry-unsafe.
- Embed runtime and cost claims in the report ID lookup: conflates separately observed evidence.
- Make evidence arguments optional: permits a weaker local release than the protected workflow.
