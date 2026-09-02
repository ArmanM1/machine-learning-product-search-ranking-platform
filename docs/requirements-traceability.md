# Requirements traceability

Status legend: **code path** means an implementation location exists or is reserved; it does not mean a test, cloud run, or acceptance gate passed. Verification status is tracked only by generated evidence.

## Guided setup

| Requirement | Implementation/evidence path | Verification |
|---|---|---|
| FR-SETUP-001 | `evidence/setup/account-checkpoint.md` | User reports tabs were opened; independent retained evidence pending |
| FR-SETUP-002 | `evidence/setup/account-checkpoint.md` | Pending |
| FR-SETUP-003 | `evidence/setup/account-checkpoint.md` | User-facing card delivered; retained evidence pending |
| FR-SETUP-004 | `docs/security.md` | Policy documented; private-boundary verification pending |
| FR-SETUP-005 | `evidence/setup/account-checkpoint.md` | Not accepted: owner declined MFA; temporary non-root access evidence also remains pending |
| FR-SETUP-006 | `infra/terraform/modules/platform/budgets.tf` | Disabled pending yes/no and email confirmation |
| FR-SETUP-007 | `docs/cost-controls.md`, manual workflow inputs | Quota/price/credit evidence pending |
| FR-SETUP-008 | `evidence/setup/account-checkpoint.md` | Pending redacted CLI identity evidence |
| FR-SETUP-009 | `docs/cloud-deployment.md` | Bounded plan written; owner authorization pending |
| FR-SETUP-010 | Setup handoff | Historical action; retained verification pending |

## Data

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-DATA-001 | `src/search_rank/data/download.py`, `prepare-data.yml` | `tests/unit/test_data_pipeline.py`; two local runs in `evidence/data/milestone-1-reproducibility.json` |
| FR-DATA-002 | `src/search_rank/data/validate.py`, `prepare-data.yml` | `tests/unit/test_data_pipeline.py`; checksummed local quality artifact in the milestone evidence |
| FR-DATA-003 | `src/search_rank/data/split.py` | `tests/unit/test_data_pipeline.py`; split counts/checksums reproduced locally, historical runs lack commit binding |
| FR-DATA-004 | `src/search_rank/features/product_text.py` | `tests/unit/test_data_pipeline.py`; versioned template identity in the generated manifest |
| FR-DATA-005 | `src/search_rank/data/validate.py` | Measured counts in `docs/data-card.md` and milestone evidence |
| FR-DATA-006 | `src/search_rank/data/prepare.py`, `prepare-data.yml` | Byte-identical local artifact checksums recorded; cloud publication pending |
| FR-DATA-007 | `src/search_rank/data/prepare.py` | `docs/data-card.md`, `evidence/data/milestone-1-reproducibility.json`; independent commit-bound review pending |

## Baselines and training

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-ML-001 | `src/search_rank/baselines/`, `baseline.yml` | `tests/unit/test_baselines.py`; one full validation scoring run in `evidence/baselines/milestone-2-validation.json`, second independent run pending |
| FR-ML-002 | `src/search_rank/training/mine_hard_examples.py` | `tests/unit/test_training_data.py`; miner artifact pending |
| FR-ML-003 | `src/search_rank/training/trainer.py` | Tiny-overfit and candidate run evidence pending |
| FR-ML-004 | `src/search_rank/training/callbacks.py`, `checkpoints.py` | Checkpoint fixture/run manifest pending |
| FR-ML-005 | Experiment configs and trainer | Both validation ablation reports pending |
| FR-ML-006 | Run artifact contract | `evidence/README.md`; generated run pending |
| FR-ML-007 | Artifact/model loader | Fresh-process load tests and serving checksum evidence pending |

## Evaluation and promotion

| Requirement | Code path | Test/evidence path |
|---|---|---|
| FR-EVAL-001 | `src/search_rank/evaluation/metrics.py` | `tests/unit/test_metrics.py`; identical-candidate assertion pending |
| FR-EVAL-002 | `metrics.py`, `bootstrap.py` | Hand fixtures in unit tests; held-out report pending |
| FR-EVAL-003 | `slices.py`, `examples.py`, `report.py` | `docs/failure-analysis.md`; generated report pending |
| FR-EVAL-004 | `latency.py` | Performance evidence pending |
| FR-EVAL-005 | CLI/evaluator guard and `.github/workflows/release.yml` | Consecutive per-job counters and refusal tests pending |
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
| FR-API-005 | Serving public-run route | Schema/redaction tests pending |
| FR-API-006 | Serving response schemas | `tests/unit/test_schemas_api.py`; end-to-end provenance pending |
| FR-UI-001 | `web/src/pages/OverviewPage.tsx` | Web unit/e2e tests pending final run |
| FR-UI-002 | `web/src/pages/ComparisonPage.tsx` | `web/tests/ComparisonPage.test.tsx`; final run pending |
| FR-UI-003 | `web/src/pages/EvaluationPage.tsx` | Web tests; report integration pending |
| FR-UI-004 | `web/src/pages/FailuresPage.tsx` | Web tests; generated failures pending |
| FR-UI-005 | `web/src/pages/ExperimentPage.tsx` | Web tests; provenance integration pending |

## Cloud and operations

| Requirement | Implementation path | Required evidence |
|---|---|---|
| FR-CLOUD-001 | ECR module, Dockerfiles, `build-images.yml` | Three immutable digests and scans |
| FR-CLOUD-002 | Training IAM/storage, `train.yml` | Completed one-instance Spot Training job manifest |
| FR-CLOUD-003 | Processing IAM/storage, `release.yml` | Two completed separately counted clean Processing jobs plus bound report |
| FR-CLOUD-004 | `storage.tf`, `prepare-data.yml` | Applied versioning/lifecycle inspection and immutable cloud-object checksum evidence pending |
| FR-CLOUD-005 | `serving.tf`, `bootstrap-baseline.yml`, `deploy.yml` | Baseline bundle, API/Lambda/CloudFront smoke, and public URL |
| FR-CLOUD-006 | `infra/terraform/` | Format/validate passed locally; apply/plan evidence pending |
| FR-CLOUD-007 | `iam.tf` | Applied trust-policy inspection and fork-denial test |
| FR-CLOUD-008 | Lambda aliases/S3 versions/ECR retention, `deploy.yml` | Successful rollback artifact |
| FR-CLOUD-009 | `docs/teardown.md` | Verified disposable-environment destroy evidence |
| FR-CLOUD-010 | One versioned CLI/image path plus bounded instance choices in `train.yml` | Completed CPU and authorized GPU parity evidence as applicable |
| FR-CLOUD-011 | `latency.py`, `deploy.yml`, `benchmark-serving.yml`, logs/metrics | First-observed and warm reports implemented; a controlled cold-start claim remains pending |

## Updating this table

Do not change a row to “verified” based on source presence. Add the evidence URI, SHA-256, producing command/workflow run, timestamp, and reviewer. If the requirement cannot be verified, preserve the reason and the smallest next action.
