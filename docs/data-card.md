# Data card: Amazon Shopping Queries ESCI

Status: the commit-bound cloud preparation completed and published its content-addressed artifact set; source-license review is complete. Final model evaluation remains pending.

## Intended use

This project uses the Amazon Shopping Queries ESCI Query-Product Ranking task to study offline reranking of supplied product candidates for US-English queries. It does not create a full-catalog search index or support live commerce decisions.

Default selection:

- `small_version = 1`
- `product_locale = "us"`
- official task/split metadata retained
- query group is the splitting and evaluation unit
- public API candidates capped at 40

## Source and terms

Canonical source: the official `amazon-science/esci-data` repository and its documented data release. The pinned repository uses Apache License 2.0 and includes an Amazon NOTICE. The detailed review is in `docs/license-review.md`.

- [x] Record source URL, immutable revision, filenames, sizes, and SHA-256 checksums.
- [x] Record dataset license and attribution requirements.
- [x] Permit only a bounded, attributed curated subset in the public demo.
- [x] Keep raw and processed tables out of Git even though the license permits conditional redistribution.
- [x] Publish download/preparation code and checksums instead of bulk records.

The project does not claim Amazon affiliation or trademark rights. Every deployed bundle still requires an exact attribution and inventory check.

## Required source fields

The preparation contract expects query identifier/text, product identifier, ESCI label, product locale, product title, official split metadata, and documented product join keys. Brand, bullet points, description, source, and category-like fields are optional only where the source schema permits.

The join must validate cardinality. Missing identifiers, empty normalized query text, unknown labels, conflicting duplicate query-product rows, cross-split query leakage, source-file absence, and checksum mismatch are fatal.

## Normalization

Normalization is deterministic and versioned. It preserves the source text separately from model input, normalizes Unicode/whitespace consistently, and does not use benchmark labels to construct text. Two required product representations are:

- `title_v1`: normalized title only.
- `enriched_v1`: labeled segments for title, brand, bullet points, and description, omitting missing segments deterministically and respecting the model’s maximum token length.

The report must count truncation, missing optional fields, duplicates, dropped rows, join loss, and queries without a positive-gain candidate.

## Label contract

`project_graded_v1` is a project-defined ordinal mapping, not an asserted Amazon evaluator:

| ESCI label | Gain | Training target |
|---|---:|---:|
| Exact | 3 | 1.0000 |
| Substitute | 2 | 0.6667 |
| Complement | 1 | 0.3333 |
| Irrelevant | 0 | 0.0000 |

## Split policy

1. Preserve the official train/test boundary.
2. Derive validation from official training queries only, using stable hashing, a versioned salt, and 10% of unique training queries by default.
3. Never move an official test query to train or validation.
4. Assert zero `query_id` overlap across all splits.
5. Store sorted query-ID hashes and query/row/product counts.
6. Draw development fixtures only from train and validation.
7. Keep official test content inaccessible to model-selection commands.

## Required measured fields

Populate from `DatasetManifest`, never by hand:

| Field | Value |
|---|---|
| Source revision | `7916cdf6ab75a462e77f20ab40428a10923998d5` |
| Source file SHA-256 values | examples `4a735b…4263a`; products `251244…5a265`; sources `a5fed8…778c50` (full values in the generated manifest) |
| Canonical split-manifest identity | `sha256:fa7dba0f7e4676e0c386efff0f6e4e184880de10abed683126dddc32c662f528` (`query-split-manifest-v1`) |
| Current semantic processed-dataset identity | `sha256:814e06ceba032871d1cac66cd4dd59177f4348c9928fdf417f2a2f3218a29525` |
| Current immutable key prefix | `data/processed/814e06ceba032871d1cac66cd4dd59177f4348c9928fdf417f2a2f3218a29525` |
| Cloud preparation evidence | [Sanitized receipt](../evidence/cloud/live-data-preparation.json) · [workflow definition](../.github/workflows/prepare-data.yml) |
| Historical pre-split-contract identity | `sha256:420735e9…e24f6` (`DatasetManifest.processed_checksum` from the earlier local evidence run) |
| Historical serialized `manifest.json` transport SHA-256 | `sha256:3f6902e7…4cf09d`; this is not either semantic identity |
| Train queries/rows/products | 18,831 / 378,153 / 320,610 |
| Validation queries/rows/products | 2,057 / 41,500 / 40,431 |
| Held-out queries/rows/products | 8,956 / 181,701 / 164,900; aggregate preparation counts only, not model-selection access |
| Label distributions | Train-and-validation diagnostic: Exact 181,819; Substitute 147,628; Complement 19,090; Irrelevant 71,116 |
| Missing optional fields | Recorded in `evidence/data/milestone-1-reproducibility.json`; no required title/source fields missing |
| Duplicate/conflict counts | Zero duplicate rows dropped; conflict validation passed |
| Dropped rows and reasons | 0 duplicate rows |
| Join cardinality delta | 0 missing product joins |

The cloud workflow published and read back the exact seven-file processed inventory before publishing its sanitized handoff. Its full semantic dataset identity and split identity above are the current training/release inputs. Shortened historical hashes remain display aids only and are not interchangeable with either current identity or a serialized transport hash.

## Limitations

- Offline labels and supplied candidate sets do not measure conversion or user satisfaction.
- US-English scope does not support multilingual claims.
- Product text may be stale or incomplete.
- ESCI grades are ordinal annotations; normalized targets are not purchase probabilities.
- Results apply to reranking candidate groups represented by this data release, not arbitrary catalog retrieval.
