# Reproducibility

Status: command and evidence contract. Two historical local data-preparation runs reproduced identical semantic and transport checksums, and one full validation baseline scoring run completed. Those data runs predate the initial commit and therefore have no Git identity; baseline reproducibility, cloud execution, training, held-out evaluation, and deployment remain pending.

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

Held-out evaluation is deliberately omitted from routine reproduction. It must fail locally unless the guarded release context supplies `ALLOW_HELDOUT_EVAL=1`, frozen hashes, baseline declaration, and the next access counter.

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

Validate each Terraform root with `init -backend=false` and `validate`. Container builds use `Dockerfile.train`, `Dockerfile.eval`, and `Dockerfile.serve` and must not rely on a mutable `latest` tag.

## Hash chain

Every claim traces through:

```text
source file checksums
  -> dataset manifest + sorted split-ID hashes
  -> experiment config canonical SHA-256
  -> code commit + locked dependencies + image digest
  -> run ID + selected checkpoint SHA-256
  -> two independent evaluation report SHA-256 values + consecutive test-access counts
  -> checksum-bound clean-evaluation binder report
  -> typed public evidence + release manifest + exact recursive bundle inventory
  -> serving image digest + deployment/performance evidence SHA-256
```

The validation-only branch stops before the held-out nodes: successful baseline command summary and baseline summary -> typed validation-only public evidence -> release manifest -> exact bundle inventory -> immutable initial pointer. It must never be described as verified held-out evidence.

Use canonical JSON for hash-addressed structured artifacts. Upload to S3 with SHA-256 checksum metadata and verify `ChecksumSHA256`; do not treat multipart ETags as content hashes.

## Determinism

- Seed Python, NumPy, PyTorch, samplers, workers, and query bootstrap from the versioned config.
- Use stable query-level hashing for the validation split.
- Use ascending product ID for score ties.
- Enable deterministic PyTorch algorithms for final runs and fail loudly if unsupported.
- Pin base-model and tokenizer revisions; keep `trust_remote_code=False`.
- Load the selected checkpoint in a fresh process for evaluation and serving.

Potential residual nondeterminism includes GPU kernels, hardware/driver changes, threading, Spot interruption/resume, and dependency-level numerical changes. Record rather than hide it.

## Reproduction gate

Two clean evaluations of the same frozen artifacts and hardware class must run in separate SageMaker Processing jobs/processes and differ by at most 0.002 absolute on the primary metric. Each job gets its own access-counter value. `bind-clean-evaluations` checksum-verifies both source reports/provenances, requires consecutive counters and exact immutable identity, and recomputes the release gate without reopening the held-out data. If the gate fails, do not promote; retain both source reports.

## Cloud reproduction

The manual workflows record job name, region, instance, instance count, Spot setting, maximum runtime, billed/runtime seconds when available, image digest, config/data/checkpoint hashes, output URI, and sanitized status. An AWS service may be named in a public claim only after its intended workload completed and this evidence exists.

## Expected generated outputs

| Output | Location | Current value |
|---|---|---|
| Dataset manifest | content-addressed processed directory | Reproduced in two local runs; exact IDs and checksums are in `evidence/data/milestone-1-reproducibility.json`; commit binding unavailable |
| Baseline summary | run reports | One full validation scoring run recorded in `evidence/baselines/milestone-2-validation.json`; second independent run pending |
| Baseline bootstrap command summary | protected validation-only release run | Pending |
| Candidate run manifest | run root | Pending |
| Validation/ablation report | run reports | Pending |
| Held-out report | manual release run | Pending |
| Two clean source reports/provenances | manual release run | Pending |
| Typed public evidence | `promoted/<model-id>/public-evidence.json` | Pending |
| Release manifest | `promoted/<model-id>/release-manifest.json` | Pending |
| Exact bundle inventory | `promoted/<model-id>/bundle-checksums.json` | Pending |
| Deployment evidence | `public/<release-id>/deployment-evidence.json` | Pending |
| Performance evidence | `public/<release-id>/performance/<run-id>/performance-report.json` | Pending |

Never replace `Pending` with a target or example number.
