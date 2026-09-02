# Architecture

Status: implemented as local code and Terraform configuration; no AWS resource or workload execution is claimed here.

## Product boundary

The platform reranks a supplied candidate list for a known shopping query. It does not retrieve a catalog, accept arbitrary product feeds, personalize results, or execute commerce transactions. The benchmark and public demo use curated US-English ESCI query groups with at most 40 candidates.

## Experiment flow

```text
ESCI source + recorded checksums
             |
             v
schema checks -> normalized product text -> query-level train/validation/test split
             |                                    |
             |                                    +-- locked until manual release
             v
input/random diagnostics -> BM25 -> unchanged cross-encoder
                                      |
                                      v
                         train-only difficult examples
                                      |
                                      v
                     candidate training + two ablations
                                      |
                                      v
                       frozen configuration + checksums
                                      |
                                      v
                  two separately counted clean held-out jobs
                                      |
                          +-----------+-----------+
                          |                       |
                     gate passes             gate fails
                          |                       |
                  immutable promotion      retain prior model
```

Validation is the only model-selection surface. The official test set is accessed only by the manual `release.yml` workflow after the configuration, checkpoint, baseline set, and processed-dataset identity are frozen. The two clean final evaluations run in separate SageMaker Processing jobs and consume consecutive access-counter values; two model loads inside one process do not satisfy this gate.

## AWS flow

```text
Protected GitHub environment
            |
      GitHub OIDC token
            |
            v
repository-and-environment-bound IAM role
            |
      +----------+------------------+------------------+
      |          |                  |                  |
      v          v                  v                  v
prepared S3   ECR train/eval/serve  SageMaker jobs   Terraform
dataset       |                     (run to completion) |
      |       +----------+-------------+                |
      +------------------+             |                |
                 v                                v
        private versioned S3          Lambda aliases + HTTP APIs
                 |                                |
         promoted pointer                         +-- candidate API for smoke tests
                 |                                +-- production API for public traffic
                 +-----------> serving image      |
                                                   v
private S3 site origin ----------------------> CloudFront
                                                   |
                                                   +-- /api/*, /healthz, /readyz -> API Gateway
```

All resources default to `us-east-1`. There is no NAT Gateway, load balancer, database, OpenSearch domain, SageMaker notebook, SageMaker real-time endpoint, scheduled retraining, or provisioned Lambda concurrency.

## Component boundaries

| Component | Responsibility | May read | May write |
|---|---|---|---|
| Data preparation | Validate, normalize, split, checksum | Pinned, checksummed public source | Content-addressed processed paths and sanitized handoff evidence |
| Baselines | Score identical candidate groups without weight changes | Prepared validation records only | Rankings, latency evidence, and a validation-only bootstrap handoff |
| Trainer | Mine train-only examples and fit one candidate | Train data, base model, frozen config | Run-scoped checkpoints and metrics |
| Evaluator | Metrics, query bootstrap, slices, examples, release gate | Candidate, baselines, one selected split per process | Two source reports plus one checksum-bound report |
| Promotion | Verify gate and checksums; update versioned pointer | Evaluation report and model artifact | `promoted/<model-id>/` and versioned `promoted/current.json` |
| FastAPI | Curated-query rank/compare/evidence routes | Embedded model/assets; sanitized public reports | Structured logs only |
| React | Minimalist, editorial evidence presentation | Public API | Browser state only |

## Artifact layout

```text
data/raw/<dataset-version>/
data/processed/<dataset-manifest-hash>/
runs/<run-id>/config/
runs/<run-id>/checkpoints/
runs/<run-id>/metrics/
runs/<run-id>/reports/
promoted/<model-id>/
promoted/current.json
public/<release-id>/
heldout/access-counter.json
```

Objects carry SHA-256 checksums. Final paths are immutable; only the versioned promotion pointer and held-out counter intentionally advance. Raw and model artifacts stay private unless their terms have been reviewed for redistribution.

`dataset_manifest_hash` is the semantic, content-addressed `DatasetManifest.processed_checksum` value in `sha256:<64 lowercase hex>` form. It is not the SHA-256 of `manifest.json`, whose serialized bytes may contain transport-specific paths or timestamps. Transport files and model archives have separate byte-level checksums.

## Release topology

The model and tokenizer are embedded in an immutable private ECR serving image. Lambda does not read raw training data. Terraform publishes the newest function version behind a `candidate` alias while ignoring drift on the `production` alias. The deploy workflow runs the API contract, 200-request primary latency/error gate, and staged CloudFront browser smoke before changing `production`; it then verifies the activated API and desktop/mobile/keyboard browser flow. A post-activation failure restores the prior alias, static index, and versioned model pointer.

The first deployed revision is the reproducible baseline release. It establishes a known-good rollback target before any candidate revision can be promoted.

## Operational limits

- Lambda: x86_64, 4,096 MB or less, 2,048 MB ephemeral storage or less, 30-second timeout.
- Reserved concurrency: exactly 2.
- Provisioned concurrency: no resource exists; effective value is 0.
- API Gateway default route throttle: burst 2, rate 2 requests/second.
- CloudWatch operational log retention: 7 days.
- S3 public access: blocked for both buckets; CloudFront uses origin access control.
- CloudFront: generated domain, TLS redirect, managed caching policies, API caching disabled.

Measured quality, latency, runtime, cost, and cloud-execution claims remain unavailable until their evidence gates pass.
