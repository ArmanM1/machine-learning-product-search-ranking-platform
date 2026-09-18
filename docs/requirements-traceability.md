# Requirements traceability

Status legend: **code path** means an implementation location exists or is reserved; it does not mean a test, cloud run, or acceptance gate passed. Verification status is tracked only by generated evidence.

## Guided setup

| Requirement | Implementation/evidence path | Verification |
|---|---|---|
| FR-SETUP-001 | `evidence/setup/account-checkpoint.md` | Guided account/setup steps are retained as a sanitized owner-reported chronology; no secret or private browser state is stored |
| FR-SETUP-002 | `evidence/setup/account-checkpoint.md` | Existing AWS and GitHub accounts were reused; the public repository and successful protected OIDC workflows provide the retained non-secret checkpoint |
| FR-SETUP-003 | `evidence/setup/account-checkpoint.md` | The setup decision card is retained with financial values and private identifiers redacted |
| FR-SETUP-004 | `docs/security.md`, `evidence/status.json` | External permissions boundary, private state, and production foundation are applied and passed the post-apply no-drift check; the MFA exception remains explicit |
| FR-SETUP-005 | `evidence/setup/account-checkpoint.md`, `iam.tf` | **Not accepted:** the owner declined MFA. The immutable non-root OIDC path is applied and exercised, but it is only a compensating control |
| FR-SETUP-006 | `infra/terraform/modules/platform/budgets.tf`, `budget_kill_switch.tf`, `docs/budget-kill-switch.md` | No AWS Budget object exists. Early threshold/email approval was superseded by the explicit creation/email waiver; the Terraform design requires budget-independent expiry when public serving is enabled, but no live expiry resource or trip is claimed yet |
| FR-SETUP-007 | `docs/cost-controls.md`, `validate_financial_snapshot.py`, `reserve_financial_capacity.py` | The private ledger is initialized and AWS-write workflows enforce fresh operation-bound receipts and cumulative conditional reservations. Exact balances/prices remain protected and are never asserted as current here |
| FR-SETUP-008 | `bootstrap-infrastructure.yml`, `infrastructure.yml`, `render_bootstrap_iam.py` | No static CI key exists; immutable repository OIDC customization and exact environment/workflow-bound roles were read back and exercised successfully |
| FR-SETUP-009 | `bootstrap-infrastructure.yml`, `infrastructure.yml`, `docs/cloud-deployment.md`, `evidence/status.json` | Bootstrap and the 57-resource production foundation are applied; the protected post-apply plan found no drift. Exact plan/run identifiers remain outside public evidence |
| FR-SETUP-010 | `evidence/setup/account-checkpoint.md`, `evidence/status.json` | Historical setup handoff is retained; strict Milestone 0 remains unaccepted because MFA was declined and the Budget/email gate was waived rather than passed |

## Data

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-DATA-001 | `src/search_rank/data/download.py`, `prepare-data.yml` | `tests/unit/test_data_pipeline.py`; two local runs in `evidence/data/milestone-1-reproducibility.json` |
| FR-DATA-002 | `src/search_rank/data/validate.py`, `prepare-data.yml` | `tests/unit/test_data_pipeline.py`; checksummed local quality artifact in the milestone evidence |
| FR-DATA-003 | `src/search_rank/data/split.py`, `SplitManifestIdentity`, `prepare-data.yml` | Dataset schema requires `query-split-manifest-v1`; unit tests recompute it and reject tampering, and the sanitized cloud receipt records the current published split identity |
| FR-DATA-004 | `src/search_rank/features/product_text.py` | `tests/unit/test_data_pipeline.py`; versioned template identity in the generated manifest |
| FR-DATA-005 | `src/search_rank/data/validate.py` | Measured counts in `docs/data-card.md` and milestone evidence |
| FR-DATA-006 | `src/search_rank/data/prepare.py`, `prepare-data.yml` | Cloud workflow published and read back the exact seven-file content-addressed inventory; sanitized receipt in `evidence/cloud/live-data-preparation.json` |
| FR-DATA-007 | `src/search_rank/data/prepare.py` | `docs/data-card.md`, `evidence/data/milestone-1-reproducibility.json`, and the commit-bound sanitized cloud receipt retain source, checksum, split, and remote-inventory evidence; no external review is claimed |

## Baselines and training

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-ML-001 | `src/search_rank/baselines/`, `baseline.yml` | `tests/unit/test_baselines.py`; two separate local scoring processes in `evidence/baselines/milestone-2-validation.json` reproduce exact config/data/query identity, all six quality vectors, ranks, and scores; controlled latency and clean-checkout reproduction remain pending |
| FR-ML-002 | `src/search_rank/training/mine_hard_examples.py` | `tests/unit/test_training_data.py`; miner artifact pending |
| FR-ML-003 | `src/search_rank/training/trainer.py` | Tiny-overfit plus allowlisted epoch-provenance tests; candidate run evidence pending |
| FR-ML-004 | `src/search_rank/training/callbacks.py`, `checkpoints.py` | Checkpoint fixture/run manifest pending |
| FR-ML-005 | Exact experiment configs, `scripts/trial_selection.py`, `freeze-trial-selection.yml` | Contract tests enforce treatment plus both validation-only controls, exact single-factor differences, disclosed three-trial scope, and predeclared selection; immutable cloud selection pending |
| FR-ML-006 | Training RunManifest plus immutable candidate inputs, Pydantic `TrialSelection`, and `schemas/json/trial_selection.schema.json` | Schema-parity and hash/provenance tests; three generated cloud runs and frozen selection pending |
| FR-ML-007 | Artifact/model loader | Fresh-process load tests and serving checksum evidence pending |

## Evaluation and promotion

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-EVAL-001 | `src/search_rank/evaluation/metrics.py` | `tests/unit/test_metrics.py`; identical-candidate assertion pending |
| FR-EVAL-002 | `metrics.py`, `bootstrap.py` | Hand fixtures in unit tests; held-out report pending |
| FR-EVAL-003 | `slices.py`, `examples.py`, `report.py`, held-out `EvaluationReport` validation | Unit tests enforce deterministic 5/5/3/1/1 selection and clear shortages; clean-run integration rejects incomplete held-out evidence; generated cloud report pending |
| FR-EVAL-004 | `latency.py` | Performance evidence pending |
| FR-EVAL-005 | CLI/evaluator guard and `.github/workflows/release.yml` | Release derives the split hash from the held-out DatasetManifest, binds it through both clean summaries/provenances, and rejects split mismatch in `tests/integration/test_clean_evaluation_binding.py`; live quota/counter evidence pending |
| FR-EVAL-006 | `gates.py` | `tests/unit/test_gates.py`; immutable release report pending |
| FR-EVAL-007 | Baseline bootstrap/promotion code, `bootstrap-baseline.yml`, and `release.yml` | Validation-only initial bundle and verified candidate promotion manifests pending |
| FR-EVAL-008 | `gates.py`, `release.yml` | Negative fixture exists/pending verification; live result pending |

## API and interface

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-API-001 | `src/search_rank/serving/` | Contract tests and cloud smoke evidence pending |
| FR-API-002 | Serving routes/query store | API contract tests pending |
| FR-API-003 | Serving rank route | API contract tests pending |
| FR-API-004 | Serving comparison route | API contract tests pending |
| FR-API-005 | Serving public-run route, required public split fields, and release readiness binding | Schema/OpenAPI tests require the field in both evidence modes; service tests reject public/release split mismatch; deployed evidence pending |
| FR-API-006 | Separate typed training and evaluation provenance in public evidence | Schema parity, hash binding, and anti-conflation tests; cloud values pending |
| FR-UI-001 | `web/src/pages/OverviewPage.tsx` | Web unit/e2e tests pending final run |
| FR-UI-002 | `web/src/pages/ComparisonPage.tsx` | `web/tests/ComparisonPage.test.tsx`; final run pending |
| FR-UI-003 | `web/src/pages/EvaluationPage.tsx` | Web tests; report integration pending |
| FR-UI-004 | `web/src/pages/FailuresPage.tsx` | Web tests; generated failures pending |
| FR-UI-005 | `web/src/pages/ExperimentPage.tsx`, `web/src/api/client.ts` | API-client tests preserve both evidence-mode split hashes and ExperimentPage renders a copyable non-null value; deployed integration pending |

## Cloud and operations

| Requirement | Implementation path | Required evidence |
|---|---|---|
| FR-CLOUD-001 | ECR module, Dockerfiles, `build-images.yml` | Three immutable digests and scans |
| FR-CLOUD-002 | Training IAM/storage, `train.yml` | Completed one-instance Spot Training job manifest |
| FR-CLOUD-003 | Processing IAM/storage, `release.yml`, strict `SageMakerProcessingQuotaPreflight` | Protected live probe confirmed selected Processing capacity at its recorded observation time; a fresh release probe plus two completed separately counted clean jobs and their bound report remain required |
| FR-CLOUD-004 | `storage.tf`, `prepare-data.yml` | Foundation apply/no-drift is recorded, and the sanitized data receipt verifies the immutable seven-object inventory and content identities after cloud readback; a separate public lifecycle/versioning inspection receipt is not retained |
| FR-CLOUD-005 | `serving.tf`, `budget_kill_switch.tf`, `bootstrap-baseline.yml`, `deploy.yml` | Baseline bundle, API/Lambda/CloudFront smoke, public URL, and observed automatic-expiry trip/recovery evidence |
| FR-CLOUD-006 | `infra/terraform/`, `reserve_financial_capacity.py`, `evidence/status.json` | Bootstrap and production apply completed with 57 managed resources and a clean post-apply plan; the private ledger is initialized, while conditional conflict/idempotency behavior remains covered by repository tests |
| FR-CLOUD-007 | `iam.tf`, `render_bootstrap_iam.py`, `docs/cloud-deployment.md`, `docs/security.md` | Repository OIDC customization was read back and exact workflow-bound roles were exercised from protected `main`; exact fork/wrong-workflow exclusions are covered by trust-policy construction tests rather than a live hostile run |
| FR-CLOUD-008 | Lambda aliases/S3 versions/ECR retention, `deploy.yml` | Successful rollback artifact |
| FR-CLOUD-009 | `docs/teardown.md` | Verified disposable-environment destroy evidence |
| FR-CLOUD-010 | One versioned CLI/image path plus bounded instance choices in `train.yml` | Completed CPU and authorized GPU parity evidence as applicable |
| FR-CLOUD-011 | `cold_start_evidence.py`, `deploy.yml`, `benchmark-serving.yml`, logs/metrics | Deploy proves a newly published, previously uninvoked on-demand candidate version and correlates its first rank request with CloudWatch Init Duration plus structured model-load/memory evidence; the post-deploy warm matrix excludes that sample |

## Updating this table

Do not change a row to “verified” based on source presence. Add the evidence URI, SHA-256, producing command/workflow run, timestamp, and reviewer. If the requirement cannot be verified, preserve the reason and the smallest next action.
