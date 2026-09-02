This directory is the no-model build default.

Production serving images must be built with:

  --build-arg MODEL_ARTIFACT_DIR=<release bundle directory>

The release bundle root contains release-manifest.json and curated-queries.json.
Terraform then points SEARCH_RANK_RELEASE_MANIFEST and
SEARCH_RANK_CURATED_QUERIES at their immutable in-image paths. Without those
settings the service intentionally remains not-ready.
