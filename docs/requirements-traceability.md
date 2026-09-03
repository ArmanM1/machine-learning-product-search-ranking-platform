# Requirements traceability

Status legend: **code path** means an implementation location exists or is reserved; it does not mean a test, cloud run, or acceptance gate passed. Verification status is tracked only by generated evidence.

## Guided setup

| Requirement | Implementation/evidence path | Verification |
|---|---|---|
| FR-SETUP-001 | `evidence/setup/account-checkpoint.md` | User reports tabs were opened; independent retained evidence pending |
| FR-SETUP-002 | `evidence/setup/account-checkpoint.md` | Existing AWS and GitHub accounts reused; retained redacted checkpoint pending |
| FR-SETUP-003 | `evidence/setup/account-checkpoint.md` | User-facing card delivered; retained evidence pending |
| FR-SETUP-004 | `docs/security.md` | Policy documented; private-boundary verification pending |
| FR-SETUP-005 | `evidence/setup/account-checkpoint.md`, `iam.tf` | Not accepted for MFA: owner declined it; immutable non-root OIDC path is configured and awaits workflow proof |
| FR-SETUP-006 | `infra/terraform/modules/platform/budgets.tf`, `budget_kill_switch.tf`, `docs/budget-kill-switch.md` | Owner waived AWS Budget creation/email confirmation; waiver is an exception, not a passed gate. Optional thresholds remain dormant, while public serving has budget-independent expiry within 24 hours; apply/trip evidence pending |
| FR-SETUP-007 | `docs/cost-controls.md`, `validate_financial_snapshot.py`, `reserve_financial_capacity.py` | No current credit balance is asserted here. Every AWS write needs a fresh operation-bound receipt, and every ordinary write needs a successful cumulative conditional ledger reservation; live balance/price evidence pending |
| FR-SETUP-008 | `bootstrap-infrastructure.yml`, `render_bootstrap_iam.py` | No static key exists; repository OIDC customization and state-role trust must be migrated to the exact workflow-bound subject, then redacted identity proof remains pending |
| FR-SETUP-009 | `bootstrap-infrastructure.yml`, `docs/cloud-deployment.md` | Fixed six-resource create-only plan workflow ready; exact plan hash/run evidence pending |
| FR-SETUP-010 | Setup handoff | Historical action; retained verification pending |

## Data

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-DATA-001 | `src/search_rank/data/download.py`, `prepare-data.yml` | `tests/unit/test_data_pipeline.py`; two local runs in `evidence/data/milestone-1-reproducibility.json` |
| FR-DATA-002 | `src/search_rank/data/validate.py`, `prepare-data.yml` | `tests/unit/test_data_pipeline.py`; checksummed local quality artifact in the milestone evidence |
| FR-DATA-003 | `src/search_rank/data/split.py`, `SplitManifestIdentity`, `prepare-data.yml` | Dataset schema requires `query-split-manifest-v1`; unit tests recompute it and reject tampering; historical measured runs predate this required field and remain legacy evidence |
| FR-DATA-004 | `src/search_rank/features/product_text.py` | `tests/unit/test_data_pipeline.py`; versioned template identity in the generated manifest |
| FR-DATA-005 | `src/search_rank/data/validate.py` | Measured counts in `docs/data-card.md` and milestone evidence |
| FR-DATA-006 | `src/search_rank/data/prepare.py`, `prepare-data.yml` | Byte-identical local artifact checksums recorded; cloud publication pending |
| FR-DATA-007 | `src/search_rank/data/prepare.py` | `docs/data-card.md`, `evidence/data/milestone-1-reproducibility.json`; independent commit-bound review pending |

## Baselines and training

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-ML-001 | `src/search_rank/baselines/`, `baseline.yml` | `tests/unit/test_baselines.py`; two separate local scoring processes in `evidence/baselines/milestone-2-validation.json` reproduce exact config/data/query identity, all six quality vectors, ranks, and scores; controlled latency and clean-checkout reproduction remain pending |
| FR-ML-002 | `src/search_rank/training/mine_hard_examples.py` | `tests/unit/test_training_data.py`; miner artifact pending |
| FR-ML-003 | `src/search_rank/training/trainer.py` | Tiny-overfit and candidate run evidence pending |
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
| FR-CLOUD-003 | Processing IAM/storage, `release.yml`, strict `SageMakerProcessingQuotaPreflight` | Exact `L-0307F515` applied-capacity receipt, then two completed separately counted clean Processing jobs plus bound report |
| FR-CLOUD-004 | `storage.tf`, `prepare-data.yml` | Applied versioning/lifecycle inspection and immutable cloud-object checksum evidence pending |
| FR-CLOUD-005 | `serving.tf`, `budget_kill_switch.tf`, `bootstrap-baseline.yml`, `deploy.yml` | Baseline bundle, API/Lambda/CloudFront smoke, public URL, and observed automatic-expiry trip/recovery evidence |
| FR-CLOUD-006 | `infra/terraform/`, `reserve_financial_capacity.py` | Format/validate passed locally; apply/plan plus conditional ledger create/conflict/idempotency evidence pending |
| FR-CLOUD-007 | `iam.tf`, `render_bootstrap_iam.py`, `docs/cloud-deployment.md` | Repository OIDC customization readback, applied one-workflow-per-role trust inspection, and fork/wrong-workflow denial tests pending |
| FR-CLOUD-008 | Lambda aliases/S3 versions/ECR retention, `deploy.yml` | Successful rollback artifact |
| FR-CLOUD-009 | `docs/teardown.md` | Verified disposable-environment destroy evidence |
| FR-CLOUD-010 | One versioned CLI/image path plus bounded instance choices in `train.yml` | Completed CPU and authorized GPU parity evidence as applicable |
| FR-CLOUD-011 | `cold_start_evidence.py`, `deploy.yml`, `benchmark-serving.yml`, logs/metrics | Deploy proves a newly published, previously uninvoked on-demand candidate version and correlates its first rank request with CloudWatch Init Duration plus structured model-load/memory evidence; the post-deploy warm matrix excludes that sample |

## Updating this table

Do not change a row to “verified” based on source presence. Add the evidence URI, SHA-256, producing command/workflow run, timestamp, and reviewer. If the requirement cannot be verified, preserve the reason and the smallest next action.
