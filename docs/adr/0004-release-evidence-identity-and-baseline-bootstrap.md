# ADR 0004: Release evidence identity and baseline bootstrap

- Status: accepted implementation decision
- Scope: dataset identity, clean evaluation, first public revision, and public evidence

## Decision

`dataset_manifest_hash` means the semantic `DatasetManifest.processed_checksum` in canonical `sha256:<64 lowercase hex>` form. A byte-level SHA-256 of a transported manifest, model archive, config, report, or bundle remains a separate checksum and must not be substituted for that dataset identity.

The final held-out result is produced by two distinct SageMaker Processing jobs and operating-system processes. Each job reserves and records its own consecutive test-access count before SageMaker receives the test prefix. A local post-job binder checksum-verifies both report/provenance pairs, requires exact configuration, checkpoint, dataset, baseline, image, Git, region, and hardware identity, enforces the 0.002 reproducibility tolerance, and recomputes the gate without reopening test data.

Before held-out access, a one-time protected workflow may publish a baseline-only release from the completed validation baseline evidence. That workflow has no permission to read `data/processed/*` or submit SageMaker jobs. Its typed `public-evidence.json` is explicitly `validation_only`, records test-access count zero, and prohibits held-out claims. A candidate release uses the `verified` evidence mode and can be created only by the guarded two-job path.

Every serving bundle contains `release-manifest.json`, `curated-queries.json`, `public-evidence.json`, model assets, and an exact `bundle-checksums.json` inventory. Serving readiness validates the typed evidence and binds it to the manifest.

## Consequences

- Host-specific manifest timestamps and paths cannot change dataset identity.
- A model archive transport digest and its uncompressed checkpoint-directory digest are both required and intentionally differ.
- A second model load in the first evaluator process does not count as an independent clean run.
- The baseline can be deployed and verified as a rollback target without inventing test metrics.
- The browser and API can distinguish validation-only evidence from a verified held-out release.

## Alternatives rejected

- Hashing serialized `manifest.json` bytes as dataset identity: transport paths and timestamps can vary without changing prepared content.
- Running two evaluations inside one process: shared process state is not a clean independent execution.
- Creating a baseline public envelope with fabricated test fields: violates the project truth boundary.
- Generating the public envelope with workflow `jq`: bypasses the typed source contract and cross-field validation.
