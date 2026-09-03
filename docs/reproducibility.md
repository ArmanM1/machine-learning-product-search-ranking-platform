# Reproducibility

Status: command and evidence contract. Two historical local data-preparation runs reproduced identical semantic and transport checksums. Two separate local validation scoring processes also reproduced every quality metric, rank, and score for all six baseline systems. Those baseline processes used a dirty shared worktree and their uncontrolled timings varied, so clean-checkout and latency reproducibility, cloud execution, training, held-out evaluation, and deployment remain pending.

## Supported environment

- Python 3.11 (project permits `<3.13`).
- Dependencies from committed `uv.lock`; do not resolve a new lock during a release run.
- Node 22 and `web/package-lock.json` for the interface.
- Terraform 1.10.5 or a reviewed compatible release, with committed provider lock files.
- AWS resources in `us-east-1` only.
- Exact container base-image digests required before a release image is declared immutable.

Record OS, CPU/GPU, architecture, driver/CUDA where applicable, Python/Node/Terraform versions, Git commit, lock hashes, container digest, and deterministic-mode status in each run manifest.

## Clean local setup

```powershell
git clone <repository-url>
Set-Location machine-learning-product-search-ranking-platform
uv sync --frozen --all-extras --dev
npm --prefix web ci
```

Do not place AWS keys, dataset files, model checkpoints, or private reports in the checkout.

## Stable commands

```powershell
uv run python -m search_rank.cli data prepare --config configs/data/esci-us-v1.yaml
uv run python -m search_rank.cli baseline run --config configs/experiments/baselines-v1.yaml
uv run python -m search_rank.cli train --config configs/experiments/candidate-v1.yaml
uv run python -m search_rank.cli evaluate --config configs/experiments/validation-v1.yaml
```

## Local validation baseline evidence

The original scoring process and the later full reproduction used the same canonical `baselines-v1` config hash, dataset-manifest hash, 2,057-query validation set, and zero held-out test accesses. Across 249,000 rows, all parsed non-latency fields were exactly equal. The deterministic semantic comparison reproduced both `(query_id, product_id, rank)` and `(query_id, product_id, rank, score)` hashes for every system. All six complete quality vectors were also exactly equal. The unchanged strongest system was `pretrained-cross-encoder@233902d25c440f23af6f7d6e94d2946bac0bee0a-enriched_v1` at graded nDCG@10 `0.8490371644459062` in both runs.

Raw ranking JSONL hashes are intentionally recorded separately in `evidence/baselines/milestone-2-validation.json`. They differ because `latency_ms` is serialized; exhaustive comparison found no other differing field. The local p95 values were:

| System | Original p95 (ms) | Reproduction p95 (ms) | Change |
|---|---:|---:|---:|
| BM25 enriched | 5.826660000457194 | 6.430099999852236 | +10.36% |
| BM25 title | 0.6888600004458567 | 0.7575799987534991 | +9.98% |
| Input order | 0.036100000215810724 | 0.045999998110346496 | +27.42% |
| Cross-encoder enriched | 758.3298630361438 | 881.2399574939765 | +16.21% |
| Cross-encoder title | 147.897584000001 | 230.908451469879 | +56.13% |
| Seeded random | 0.1000200009002583 | 0.12283999967621637 | +22.82% |

These were separate processes, but not controlled performance trials: both observed a dirty shared worktree, and the second run's recorded Git SHA does not bind its uncommitted state. The evidence therefore closes local quality and ranking reproducibility only. It does not claim latency reproducibility or a clean-checkout reproduction.

Held-out evaluation is deliberately omitted from routine reproduction. It must fail locally unless the guarded release context supplies `ALLOW_HELDOUT_EVAL=1`, frozen hashes, baseline declaration, and the next access counter.

Before that guarded context can exist, complete the exact three-run validation comparison and publish its immutable selection artifact. See `docs/trial-selection.md`. The protected order is treatment final run, random-negative ablation, title-only ablation, `freeze-trial-selection.yml`, then `release.yml`. The release rejects a missing or changed selection before either held-out access counter is reserved.

The first deployable revision is created without held-out access by the protected `bootstrap-baseline.yml` workflow. Its source command is:

```text
python -m search_rank.cli bootstrap-baseline-release \
  --baseline-summary <successful-baseline-command-summary> \
  --baseline-config configs/experiments/baselines-v1.yaml \
  --dataset-manifest <checksummed-manifest-evidence-copy> \
  --curated-queries <checksummed-validation-curated-queries> \
  --output-dir <new-immutable-directory> \
  --image-digest sha256:<digest> --git-sha <40-hex-commit> \
  --hardware-class <recorded-class> --region us-east-1
```

It checksum-verifies the successful validation run, records `evidence_mode=validation_only` and test-access count zero, and creates the pointer only if no prior pointer exists.

## Test and build commands

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src/search_rank
uv run pytest -m "not heldout"
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test -- --run
npm --prefix web run build
terraform -chdir=infra/terraform fmt -check -recursive
```

Validate each Terraform root with `init -backend=false` and `validate`. Container builds use `Dockerfile.train`, `Dockerfile.eval`, and `Dockerfile.serve` and must not rely on a mutable `latest` tag. The serving image build is fail-closed to `VITE_DATA_MODE=api`; it embeds `web/dist/build-config.json`, and deployment re-reads that file from the immutable registry image to prove the run, query, and model identifiers match the release before traffic can move.

## Hash chain

Every claim traces through:

```text
source file checksums
  -> dataset manifest + canonical query-split-manifest-v1 hash + sorted split-ID hashes
  -> experiment config canonical SHA-256
  -> code commit + locked dependencies + image digest
  -> three cloud run IDs + selected checkpoint SHA-256 values
  -> validation-only trial selection + both mandatory contrasts + zero test access
  -> selected training ModelArtifact + RunManifest checksums + separate training execution provenance
  -> two independent evaluation report SHA-256 values + consecutive test-access counts
  -> checksum-bound clean-evaluation binder report + separate Processing provenance
  -> evaluation-bound candidate-model-artifact.json for either gate outcome
  -> typed public evidence + release manifest + exact recursive bundle inventory
  -> serving image digest + deployment/performance evidence SHA-256
```

The validation-only branch stops before the held-out nodes: successful baseline command summary and baseline summary -> typed validation-only public evidence -> release manifest -> exact bundle inventory -> immutable initial pointer. It must never be described as verified held-out evidence. Because unchanged baselines were not trained by this platform, this branch deliberately contains no `ModelArtifact`; inventing training provenance would be less truthful than omitting an inapplicable contract.

Use canonical JSON for hash-addressed structured artifacts. Upload to S3 with SHA-256 checksum metadata and verify `ChecksumSHA256`; do not treat multipart ETags as content hashes.

## Determinism

- Seed Python, NumPy, PyTorch, samplers, workers, and query bootstrap from the versioned config.
- Use stable query-level hashing for the validation split.
- Use ascending product ID for score ties.
- Bind reproducibility to ordering: scoreless ranking hashes sort by query, rank, and product ID
  and hash each `(query_id, product_id, rank)` tuple. Input iteration order and latency do not
  affect the hash, but swapping two product ranks always does.
- Enable deterministic PyTorch algorithms for final runs and fail loudly if unsupported.
- Pin base-model and tokenizer revisions; keep `trust_remote_code=False`.
- Load the selected checkpoint in a fresh process for evaluation and serving.

Potential residual nondeterminism includes GPU kernels, hardware/driver changes, threading, Spot interruption/resume, and dependency-level numerical changes. Record rather than hide it.

## Reproduction gate

Two clean evaluations of the same frozen artifacts and hardware class must run in separate SageMaker Processing jobs/processes and differ by at most 0.002 absolute on the primary metric. Each job gets its own access-counter value. `bind-clean-evaluations` checksum-verifies both source reports/provenances, requires consecutive counters and exact immutable identity—including both `dataset_manifest_hash` and `split_manifest_hash`—and recomputes the release gate without reopening the held-out data. If the gate fails, do not promote; retain both source reports.

Workflow retries keep the GitHub run ID in every SageMaker job name and omit the run-attempt number. A rerun therefore describes the existing job, compares its complete requested configuration, environment, and exact user-tag set, waits when it is still active, reuses it only when it completed successfully, and fails on any mismatch or unsuccessful terminal state. A separate workflow dispatch receives a new GitHub run ID and may create new jobs.

Training and evaluation inputs use conditional S3 creation followed by byte-for-byte and metadata verification. Run reports, public release evidence, promoted bundles, decisions, and the frozen trial selection use the same compare-on-existing rule. Partial retries may complete an exact prior publication, but they reject changed bytes, changed metadata, unexpected objects, or a truncated/fuzzy final inventory. Held-out access uses one deterministic immutable reservation per clean job. If the mutable global counter was advanced but the reservation write was interrupted, the rerun accepts only the exact reservation bytes and never increments that clean job twice.

## Cloud reproduction

The manual workflows record job name, region, instance, instance count, Spot setting, maximum runtime, billed/runtime seconds when available, image digest, config/data/checkpoint hashes, output URI, and sanitized status. An AWS service may be named in a public claim only after its intended workload completed and this evidence exists.

The public projection intentionally omits account IDs, ARNs, private object URIs, and job locators. It binds the frozen trial-selection bytes and selected private training `RunManifest` by canonical SHA-256, then exposes only their allowlisted training fields. Evaluation/Processing fields are a separate typed object and must match the release manifest exactly.

The serving benchmark always attempts exactly 200 measured requests for each of nine conditions. Its primary latency condition (40 candidates at offered concurrency one) requires at least 199 successful responses, which makes its measured error rate strictly less than one percent. Every other measured condition requires at least 20 successes, and every condition requires at least one successful warmup. The raw report, typed contract, independent validator, validation receipt, and published claim all encode those same floors.

## Expected generated outputs

| Output | Location | Current value |
|---|---|---|
| Dataset manifest | content-addressed processed directory | Historical pre-split-identity evidence was reproduced in two local runs; a fresh run must publish the required `query-split-manifest-v1` hash and refreshed processed/transport hashes before it is current |
| Baseline summary | run reports | Two separate local validation scoring processes reproduced exact quality, ranks, and scores; controlled latency and clean-checkout evidence remain pending in `evidence/baselines/milestone-2-validation.json` |
| Baseline bootstrap command summary | protected validation-only release run | Pending |
| Candidate run manifest | run root | Pending |
| Three candidate/control run manifests | private run reports | Pending |
| Immutable validation trial selection | `runs/trial-selection/<selection-id>/trial-selection.json` | Contract/workflow implemented; cloud artifact pending |
| Held-out report | manual release run | Pending |
| Two clean source reports/provenances | manual release run | Pending |
| Evaluation-bound candidate ModelArtifact | immutable verified release bundle as `candidate-model-artifact.json` | Contract/workflow implemented; cloud artifact pending |
| Typed public evidence | initial `promoted/<model-id>/`, then immutable `promoted/releases/<release-id>/public-evidence.json` | Pending |
| Release manifest | initial `promoted/<model-id>/`, then immutable `promoted/releases/<release-id>/release-manifest.json` | Pending |
| Exact bundle inventory | initial `promoted/<model-id>/`, then immutable `promoted/releases/<release-id>/bundle-checksums.json` | Pending |
| Deployment evidence | `public/<release-id>/deployment-evidence.json` | Pending |
| Performance evidence | `public/<release-id>/performance/<run-id>/performance-report.json` | Pending |

Never replace `Pending` with a target or example number.
