# Local infrastructure and workflow validation

Date: 2026-09-02

| Check | Tool | Result |
|---|---|---|
| Terraform recursive formatting | Terraform 1.10.5 | Pass |
| Bootstrap root validation | Terraform 1.10.5, AWS provider 6.62.0 | Pass |
| Development root validation | Terraform 1.10.5, AWS provider 6.62.0, TLS provider 4.4.0 | Pass |
| Production root validation | Terraform 1.10.5, AWS provider 6.62.0, TLS provider 4.4.0 | Pass |
| GitHub workflow syntax/expressions | actionlint 1.7.12 | Pass |
| Workflow YAML parse | PyYAML in the project environment | Pass |
| Embedded workflow Python parse | Python 3.11 AST parser | Pass |
| Embedded workflow Bash parse | Git for Windows Bash `-n` | Pass (51 blocks) |
| Evidence JSON parse | Python standard library | Pass |

Terraform initialization used `-backend=false`. No AWS credentials were configured for these checks, no plan or apply ran, and no cloud-resource or workload-execution claim is unlocked.

These checks cover the current working tree before its initial commit is published. They are not commit-bound CI evidence; rerun the protected checks on the final commit before using its Git SHA in any artifact or release claim.
