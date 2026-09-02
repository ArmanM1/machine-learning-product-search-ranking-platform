# Dataset and model license review

Reviewed: 2026-09-02. This engineering record is not legal advice.

## Amazon Shopping Queries ESCI

- Source: `amazon-science/esci-data` at commit `7916cdf6ab75a462e77f20ab40428a10923998d5`.
- License source: <https://github.com/amazon-science/esci-data/blob/7916cdf6ab75a462e77f20ab40428a10923998d5/LICENSE>
- Notice source: <https://github.com/amazon-science/esci-data/blob/7916cdf6ab75a462e77f20ab40428a10923998d5/NOTICE>
- Verified license: Apache License 2.0. The pinned repository's `NOTICE` says, “Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.”

The license permits use, modification, and redistribution subject to its conditions. Any redistributed source-derived content must retain applicable copyright, attribution, license, and NOTICE material; modified files must be identified where required. The license does not grant Amazon trademark rights.

Project policy is narrower than the available permission:

- Raw and processed tables remain gitignored and are not published in this repository.
- The public product may contain only a small, checksummed curated subset required for the comparison demo.
- The repository includes the upstream attribution in `NOTICE` and does not claim Amazon affiliation or an official competition result.
- Any later broad dataset or checkpoint publication requires a fresh review of the exact artifact.

## Cross-encoder checkpoint

- Model: `cross-encoder/ms-marco-MiniLM-L6-v2`.
- Revision: `233902d25c440f23af6f7d6e94d2946bac0bee0a`.
- Model source: <https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/tree/233902d25c440f23af6f7d6e94d2946bac0bee0a>
- Verified model-card license metadata: `apache-2.0` from the Hugging Face model API for the exact revision; the repository is public and ungated.

The project may use and fine-tune the pinned checkpoint under Apache-2.0 obligations. Model weights are not committed to Git. Cloud images and promoted checkpoints remain private unless a later release explicitly includes the required license and NOTICE material and passes a new distribution review.

## Project code

Original project code is MIT-licensed. The MIT license does not replace or weaken the separate obligations attached to the dataset, checkpoint, or third-party dependencies.

## Review outcome

The planned local experiment, private cloud workload, and bounded attributed public comparison are permitted under the recorded upstream licenses. This closes the source-license identification task, while each actual public bundle must still be checked for attribution and exact file inventory before deployment.
