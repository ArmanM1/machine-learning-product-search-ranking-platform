# Validation trial selection

Status: the contract and protected workflow are implemented; no cloud training or validation result is claimed until the immutable artifacts described here exist.

## Frozen comparison

The release candidate is not chosen by taking the largest observed validation score. The only promotion-eligible treatment is preregistered as `candidate_treatment` and uses `configs/experiments/candidate-v1.yaml`. Two validation-only, non-promotable controls must be present:

| Role | Frozen config | Only intended experimental change |
|---|---|---|
| `candidate_treatment` | `candidate-v1.yaml` | Enriched text and mixed difficult/random negatives |
| `random_negative_control` | `candidate-random-ablation-v1.yaml` | Random-only sampling, with the enriched input otherwise retained |
| `title_only_control` | `candidate-title-ablation-v1.yaml` | Title-only input, with mixed difficult/random sampling otherwise retained |

The immutable selection artifact records exactly three official final-comparison trials, both predeclared contrasts, each validation nDCG@10 value, and each treatment-minus-control delta. Its `trial_count` describes this complete frozen comparison. It is not permission to omit a separate exploratory validation run from its own run manifest. The preregistered treatment remains selected even if either control has a larger observed validation score.

## Required order

1. Copy `docs/workflow-inputs/train.example.json`, replace every placeholder, and dispatch `train.yml` at one clean `main` commit for the treatment with `run_kind=final`. The committed config fixes `training_config_role=candidate_treatment`.
2. Repeat with the random-negative config, `run_kind=ablation`, and its committed `training_config_role=random_negative_control`.
3. Repeat with the title-only config, `run_kind=ablation`, and its committed `training_config_role=title_only_control`.
4. Retain each run's immutable `candidate-release-inputs.json`, `run-manifest.json`, and model archive key plus SHA-256.
5. Dispatch `freeze-trial-selection.yml` with the three candidate-release-input keys and byte-level SHA-256 values. Type the exact authorization phrase only after reviewing those sources.
6. Copy `docs/workflow-inputs/release.example.json`, replace its frozen fields including `trial_selection_s3_key` and `trial_selection_sha256`, and pass the compact JSON to `release.yml`. The release workflow verifies the selection before it captures the baseline pointer, reserves either access-counter value, or submits a SageMaker Processing job.

`freeze-trial-selection.yml` sets `ALLOW_HELDOUT_EVAL=0`. It never downloads `test.parquet`, and the model-archive reader rejects held-out/test filenames. The artifact itself must say `split=validation`, `test_access_count=0`, and `heldout_accessed=false`.

## What is bound

`scripts/trial_selection.py` checks and binds all of the following for every role:

- candidate-input JSON key and checksum;
- model archive key and checksum, selected checkpoint checksum, training summary checksum, and exact frozen-config bytes;
- authoritative cloud training RunManifest key and checksum;
- clean Git commit, exact commit-tagged ECR image digest, dataset-manifest hash, region, hardware, accelerator, and successful SageMaker job identity;
- the exact committed role/config mapping and the intended single-factor config differences.

The training container may report `git_sha=unavailable` because the image intentionally lacks `.git`. It may never report a different commit. Source identity is authoritative only when the checksummed cloud RunManifest binds the clean checkout, exact `sha-<commit>` ECR tag/digest, and SageMaker job evidence.

The selection ID is derived from the Git SHA and the three candidate-input, RunManifest, and model-archive hashes. Publication uses an S3 conditional create, so an existing selection object cannot be overwritten. The release makes a public evidence copy only after the guarded evaluation outcome is available; raw model archives and private training inputs remain private.

## Selection and claim rules

- The selected role is always `candidate_treatment`; observed control metrics cannot substitute another model.
- The two controls are evidence about sampling and input text, not additional release candidates.
- Every exploratory validation run still requires its own immutable training evidence. Do not describe the three-trial artifact as a count of unrelated development attempts.
- Optional ablations require an explicit documented extension; they cannot replace either mandatory control or alter the frozen selected candidate.
- Before a successful live freeze, `evidence/training/trial-selection.pending.json` is only a pending marker and contains no result.
- A workflow artifact is not durable evidence by itself. The S3 key, SHA-256, workflow run URL, timestamp, and reviewer must be retained in the milestone evidence.

The freeze workflow reserves a conservative USD 0.25 credit-covered allowance for S3 reads and publication and refuses if the campaign or credit-reserve guard fails. That allowance is a gate, not a billing guarantee. Training and release jobs have their own separately authorized cost checks.
