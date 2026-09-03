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
 workflow-bound GitHub OIDC token
            |
            v
repository/environment/workflow-bound IAM role
            |
            v
signed snapshot -> conditional private S3 ledger reservation
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

All resources default to `us-east-1`. There is no NAT Gateway, load balancer, database, OpenSearch domain, SageMaker notebook, SageMaker real-time endpoint, scheduled retraining, or provisioned Lambda concurrency. When public serving exists, a budget-independent EventBridge schedule trips the exact Lambda/CloudFront shutdown handler within 24 hours. Optional AWS Budget triggers remain disabled under the owner waiver.

## Component boundaries

| Component | Responsibility | May read | May write |
|---|---|---|---|
| Data preparation | Validate, normalize, split, checksum | Pinned, checksummed public source | Content-addressed processed paths and sanitized handoff evidence |
| Financial authorization | Bind the current observation to one workflow, commit, and dispatch; atomically reserve cumulative capacity | Protected snapshot and private S3 ledger | One conditional, idempotent ledger reservation |
| Baselines | Score identical candidate groups without weight changes | Prepared validation records only | Rankings, latency evidence, and a validation-only bootstrap handoff |
| Trainer | Mine train-only examples and fit one candidate | Train data, base model, frozen config | Run-scoped checkpoints and metrics |
| Evaluator | Metrics, query bootstrap, slices, examples, release gate | Candidate, baselines, one selected split per process | Two source reports plus one checksum-bound report |
| Release decision/publication | Verify gate, frozen trial selection, selected training RunManifest and ModelArtifact, and evaluation checksums; publish either a candidate promotion or honest negative outcome without changing production | Evaluation report, selected training provenance, prior pointer, and model artifact | Held-out `promoted/releases/<release-id>/` with `candidate-model-artifact.json`, plus immutable `promoted/decisions/<release-id>.json` |
| Deployment/activation | Verify the staged decision and bundle, smoke the staged API/site, activate production, and only then advance the live pointer | Immutable release bundle, staged decision, and prior production state | Initial `promoted/<model-id>/`, versioned `promoted/current.json`, deployment evidence, and rollback state |
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
promoted/releases/<release-id>/
promoted/decisions/<release-id>.json
promoted/current.json
public/<release-id>/
heldout/access-counter.json
```

Objects carry SHA-256 checksums. Final paths and release decisions are immutable; only the versioned current-release pointer and held-out counter intentionally advance. Release never advances the live pointer: deployment does so only after production activation and verification. A failed held-out gate publishes a new release-specific evidence bundle whose active model remains the prior baseline. Raw and model artifacts stay private unless their terms have been reviewed for redistribution.

Verified release manifests bind two non-interchangeable public provenance objects. `training` is derived from the candidate-treatment entry in the frozen three-trial selection plus its checksummed training `RunManifest`; `evaluation` is derived from the two clean Processing jobs. The UI and API never sum their durations or attribute both costs to either hardware class.

The release also creates one immutable final `candidate-model-artifact.json` for both possible
gate outcomes. It copies the training-time identities without reinterpretation and checksum-binds
the source ModelArtifact, selected RunManifest, and final evaluation report. A retained-negative
release records `promoted=false` while still preserving the evaluated candidate for audit and
comparison. Validation-only baseline bundles contain unchanged systems and therefore do not claim
the trained-model contract.

`dataset_manifest_hash` is the semantic, content-addressed `DatasetManifest.processed_checksum` value in `sha256:<64 lowercase hex>` form. It covers every non-transport manifest field—including source revision and raw checksums, licensing identity, preprocessing version, split strategy and query-ID hashes, counts, label distribution, missingness, and dropped-row diagnostics—plus the exact checksum index for every generated data artifact. Only the circular checksum field, transport URI, and creation timestamp are excluded. It is not the SHA-256 of `manifest.json`; transport files and model archives have separate byte-level checksums.

`split_manifest_hash` is a distinct, required `query-split-manifest-v1` identity. Its canonical payload contains the identity version, dataset name/version, source revision, locale, raw source checksums, preprocessing version, split strategy, split-salt hash, per-split counts, per-split sorted query-ID hashes, and total row/query counts. It is not a hash of serialized `manifest.json`. The broader processed-dataset identity includes this split identity and all prepared artifact checksums, while the split identity is propagated separately so two executions cannot claim the same frozen query assignment without presenting the exact split evidence.

## Release topology

The model and tokenizer are embedded in an immutable private ECR serving image. Lambda does not read raw training data. Terraform publishes the newest function version behind a `candidate` alias while ignoring drift on the `production` alias. A workflow-attempt-and-release nonce changes only the Lambda configuration identity, so a retry of the same immutable image and serving Git revision still receives a fresh, previously uninvoked numeric version. The release Git SHA identifies the code that assembled and verified the release bundle; the serving Git SHA separately identifies the checkout used to build the runtime image, and both are verified against their own immutable artifacts rather than incorrectly required to be equal.

The deploy workflow first inspects Terraform state. An existing public surface remains enabled during later reconciliations, but a first deployment creates only the Lambda versions, aliases, and IAM-authenticated candidate API. Before any public API, Lambda permission, site bucket policy, or CloudFront resource exists, the workflow proves the candidate version is new, on-demand, backed by the exact resolved ECR URI and digest, and has no earlier CloudWatch events. It correlates the first rank request with the Lambda initialization report and structured startup/request measurements, then runs the API contract and a separately warmed 200-request latency/error gate. Only after those gates pass may a second no-delete/no-replacement Terraform plan create the public surface; that plan must leave the already-tested private runtime resources unchanged.

Staged browser requests map every static URL to the immutable `releases/<release-id>/` prefix, so no live-root object changes. Because the public CloudFront API origin targets `production`, the same-origin staged browser check uses a brief revision-ID-CAS canary transition and immediately restores the exact captured alias revision; a restoration failure disables Lambda traffic and is retried by final compensation. Durable activation then CAS-moves the alias, copies the complete static release, verifies the exact CloudFront root and every release object byte plus desktop/mobile/keyboard flows, and only afterward advances the model pointer. Activation and manual rollback install `EXIT`, `INT`, and `TERM` compensation before their first mutation; cancellation preserves the original failure status while attempting to restore alias, static bytes, and pointer, and disables Lambda traffic if coherent restoration cannot be proved. Immediately before evidence publication the workflow re-observes the exact production alias revision and resolved runtime image. Any later failure restores the prior alias, full static release, and pointer; an unrecognized concurrent revision is never overwritten. The canonical deployment-evidence key is itself versioned and advances with an ETag precondition, so a retry can record its new Lambda version without erasing earlier successful observations.

The first deployed revision is the reproducible baseline release. It establishes a known-good rollback target before any candidate revision can be promoted.

## Operational limits

- Lambda: x86_64, 4,096 MB or less, 2,048 MB ephemeral storage or less, 30-second timeout.
- Reserved concurrency: exactly 2.
- Provisioned concurrency: no resource exists; effective value is 0.
- API Gateway default route throttle: burst 2, rate 2 requests/second.
- CloudWatch operational log retention: 7 days.
- S3 public access: blocked for both buckets; CloudFront uses origin access control.
- CloudFront: generated domain, TLS redirect, managed caching policies, API caching disabled.
- Public-serving expiry: first automatic shutdown invocation within 24 hours; recovery is manual and Terraform does not silently restore a tripped surface.
- Financial envelope: signed operation-specific snapshot plus conditional cumulative ledger reservation. Billing lag, trigger delivery, and already-incurred requests mean this is not a hard USD 0 guarantee.

Measured quality, latency, runtime, cost, and cloud-execution claims remain unavailable until their evidence gates pass.
