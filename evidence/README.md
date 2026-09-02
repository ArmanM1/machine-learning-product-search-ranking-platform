# Evidence registry

This directory indexes proof produced by reproducible runs. It does not contain target metrics presented as results.

## Rules

1. Generated artifacts use immutable run/release IDs and SHA-256 checksums.
2. `status.json` is the public claim boundary. `null` means not measured or not verified; never replace it with a PRD target.
3. Raw data, private product text, model checkpoints, account identifiers, billing exports, and signed URLs do not belong here.
4. Large artifacts remain in private versioned S3; commit a sanitized manifest/checksum and durable permitted URL only.
5. A cloud service is marked executed only when its intended workload completed and a sanitized job/deployment artifact exists.
6. A held-out metric is recorded only from the counted manual release report.
7. Negative results, failed gates, excluded queries, and regressions remain visible.

## Expected evidence sets

```text
setup/account-checkpoint.md
data/<dataset-manifest-hash>.json
runs/<run-id>/run-manifest.json
runs/<run-id>/validation-report.json
releases/<release-id>/baseline-summary.json                 # validation-only mode
releases/<release-id>/clean-1/{command-summary,evaluation-report,evaluation-provenance,processing-job-evidence}.json
releases/<release-id>/clean-2/{command-summary,evaluation-report,evaluation-provenance,processing-job-evidence}.json
releases/<release-id>/access-counter-{1,2}.json
releases/<release-id>/evaluation-report.json                # verified mode, bound pair
releases/<release-id>/evaluation-provenance.json            # verified mode, bound pair
releases/<release-id>/public-evidence.json
releases/<release-id>/bundle-checksums.json
releases/<release-id>/release-manifest.json
releases/<release-id>/deployment-evidence.json
releases/<release-id>/performance/<workflow-run>/performance-report.json
releases/<release-id>/rollback-evidence.json
cloud/cost-evidence.json
cloud/teardown-evidence.json
```

Only templates and explicit pending markers are committed before runs.

A validation-only baseline release substitutes `baseline-summary.json` for `evaluation-report.json`, records `evidence_mode=validation_only`, and records a zero test-access count. It also retains the successful baseline and bootstrap command summaries. A verified candidate release uses the checksum-bound two-job evaluation report. Both modes require `public-evidence.json`, `release-manifest.json`, and the exact recursive `bundle-checksums.json` inventory.

Local evidence currently includes two byte-identical data-preparation runs in `data/milestone-1-reproducibility.json` and one complete validation baseline scoring run in `baselines/milestone-2-validation.json`. The data evidence records that no commit identity was available for those historical runs. The baseline evidence explicitly withholds a reproducibility claim until a second independent full scoring run exists. Neither file is cloud, held-out, promotion, or deployment evidence.
