# Compact manual-workflow inputs

GitHub accepts at most ten `workflow_dispatch` inputs. The training, held-out release, and
baseline-bootstrap workflows therefore accept one exact JSON object for their immutable evidence
and cost fields, plus the small human authorization fields that must remain visually separate.

Copy the matching example, replace every placeholder with the reviewed value from the immediately
preceding immutable artifact, and send it as one line. For example:

```bash
jq -c . docs/workflow-inputs/train.example.json > /tmp/train-dispatch.json
gh workflow run train.yml --ref main \
  -f dispatch_config="$(cat /tmp/train-dispatch.json)" \
  -f authorization='SUBMIT ONE SAGEMAKER TRAINING JOB'
```

For the two other workflows, use `release.example.json` or `bootstrap-baseline.example.json` and
their exact authorization phrase. Release also requires `-f allow_heldout_eval=1` after the frozen
inputs and access counter have been reviewed.

The examples are templates, not runnable evidence. Do not reuse their placeholder hashes, object
keys, counters, prices, or run IDs. The validator runs before AWS authentication or package
installation and rejects the whole object unless:

- its keys exactly match the workflow contract, with no missing, extra, or duplicate key;
- every value is a non-empty JSON string without control characters;
- paths, IDs, SHA-256 values, image digests, decimals, and integers match strict formats;
- config roles, hardware/accelerator pairs, baseline membership, and runtime ceilings agree; and
- protected bucket and ECR variables are present and valid before derived URIs are exported.

The release object also carries the exact committed baseline-config path and byte checksum. Before
held-out access, the release workflow requires the baseline command to come from the same clean Git
commit being evaluated and recomputes the baseline config's semantic hash from those checked-out
bytes. A baseline run from an older commit, a dirty tree, or different config fails closed.

Only after all checks pass are the normalized values appended to `GITHUB_ENV`. The workflow records
a canonical `DISPATCH_CONFIG_SHA256`, so reviewers can bind the unpacked input set without relying
on JSON whitespace or key order. Current campaign spend and remaining applicable credit stay in
protected environment secrets and are never accepted from the dispatch JSON. The protected observation
time, USD reservation/remaining commitment, CPU/GPU reservation and usage counters, HMAC key, and version-2
receipt described in `docs/cloud-deployment.md` also never belong in these examples. The receipt binds the
full canonical workflow input object, including this JSON and the separate authorization fields, to one
workflow, commit, and financial observation. Changing any input requires a new receipt. Sanitized provenance
is schema-validated and rechecked against the non-overridable six-hour TTL at every protected mutation
boundary; the exact operation must also hold its conditional private-ledger reservation before the first
ordinary AWS write.
