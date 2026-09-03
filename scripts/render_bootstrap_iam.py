"""Render and validate the external IAM artifacts used before Terraform can assume control.

The generated documents contain no credentials. Account IDs are supplied at execution time and
are used only to construct deterministic ARNs. The permissions boundary and seed role are
deliberately external to the platform Terraform state so no Terraform-created role can mutate its
own maximum permissions.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Literal, cast

DocumentKind = Literal["boundary", "platform-seed-policy", "state-policy", "trust"]
Environment = Literal["dev", "prod"]
TrustPurpose = Literal["platform-seed", "state-bootstrap"]

PROJECT = "product-search-ranking"
DEFAULT_ENVIRONMENT: Environment = "prod"
REGION = "us-east-1"
STATE_ROLE_NAME = "product-search-github-bootstrap"
REPOSITORY_NAME = "machine-learning-product-search-ranking-platform"

ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
ID_RE = re.compile(r"^[1-9][0-9]{0,19}$")
OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

APPROVED_BOUNDARY_WILDCARDS = {
    "apigateway:*",
    "budgets:*",
    "cloudfront:*",
    "cloudwatch:*",
    "ecr:*",
    "events:*",
    "lambda:*",
    "logs:*",
    "s3:Get*",
    "s3:List*",
    "s3:Put*",
    "sagemaker:*",
    "sns:*",
}

STATE_BUCKET_READ_ACTIONS = {
    "s3:GetAccelerateConfiguration",
    "s3:GetBucketAcl",
    "s3:GetBucketCORS",
    "s3:GetBucketLogging",
    "s3:GetBucketObjectLockConfiguration",
    "s3:GetBucketPolicy",
    "s3:GetBucketRequestPayment",
    "s3:GetBucketWebsite",
    "s3:GetReplicationConfiguration",
}


def _validate_identity(account_id: str, owner: str, owner_id: str, repository_id: str) -> None:
    if not ACCOUNT_RE.fullmatch(account_id):
        raise ValueError("account_id must be exactly 12 decimal digits")
    if not OWNER_RE.fullmatch(owner):
        raise ValueError("repository owner is invalid")
    if not ID_RE.fullmatch(owner_id) or not ID_RE.fullmatch(repository_id):
        raise ValueError("GitHub owner and repository IDs must be positive decimal IDs")


def _validate_environment(environment: str) -> Environment:
    if environment not in {"dev", "prod"}:
        raise ValueError("environment must be exactly dev or prod")
    return cast(Environment, environment)


def boundary_name(environment: Environment = DEFAULT_ENVIRONMENT) -> str:
    return f"{PROJECT}-{_validate_environment(environment)}-permissions-boundary"


def seed_role_name(environment: Environment = DEFAULT_ENVIRONMENT) -> str:
    return f"product-search-github-platform-seed-{_validate_environment(environment)}"


# Backward-compatible aliases for callers that mean the production bootstrap artifacts.
BOUNDARY_NAME = boundary_name()
SEED_ROLE_NAME = seed_role_name()


def _role_names(environment: Environment = DEFAULT_ENVIRONMENT) -> tuple[str, ...]:
    environment = _validate_environment(environment)
    return (
        f"{PROJECT}-{environment}-sagemaker-training",
        f"{PROJECT}-{environment}-sagemaker-processing",
        f"{PROJECT}-{environment}-lambda",
        f"{PROJECT}-{environment}-budget-kill-switch",
        f"{PROJECT}-{environment}-github-production",
        f"{PROJECT}-{environment}-github-aws-baseline",
        f"{PROJECT}-{environment}-github-aws-data",
        f"{PROJECT}-{environment}-github-aws-images",
        f"{PROJECT}-{environment}-github-aws-infrastructure",
        f"{PROJECT}-{environment}-github-aws-training",
        f"{PROJECT}-{environment}-github-aws-trial-selection",
        f"{PROJECT}-{environment}-github-baseline-release",
        f"{PROJECT}-{environment}-github-heldout-release",
        f"{PROJECT}-{environment}-github-production-benchmark",
    )


def _arns(account_id: str, environment: Environment = DEFAULT_ENVIRONMENT) -> dict[str, Any]:
    environment = _validate_environment(environment)
    state_bucket = f"{PROJECT}-terraform-state-{account_id}-{REGION}"
    artifact_bucket = f"{PROJECT}-{environment}-{account_id}-{REGION}-artifacts"
    site_bucket = f"{PROJECT}-{environment}-{account_id}-{REGION}-site"
    state_key = f"{PROJECT}/{environment}/terraform.tfstate"
    roles = [f"arn:aws:iam::{account_id}:role/{name}" for name in _role_names(environment)]
    infrastructure_role = (
        f"arn:aws:iam::{account_id}:role/{PROJECT}-{environment}-github-aws-infrastructure"
    )
    name = f"{PROJECT}-{environment}"
    return {
        "account": account_id,
        "environment": environment,
        "name": name,
        "boundary": f"arn:aws:iam::{account_id}:policy/{boundary_name(environment)}",
        "seed_role": f"arn:aws:iam::{account_id}:role/{seed_role_name(environment)}",
        "state_bucket": f"arn:aws:s3:::{state_bucket}",
        "state_object": f"arn:aws:s3:::{state_bucket}/{state_key}",
        "state_lock": f"arn:aws:s3:::{state_bucket}/{state_key}.tflock",
        "financial_ledger": f"arn:aws:s3:::{state_bucket}/cost-control/ledger.json",
        "artifact_bucket": f"arn:aws:s3:::{artifact_bucket}",
        "site_bucket": f"arn:aws:s3:::{site_bucket}",
        "roles": roles,
        "workload_roles": roles[:4],
        "infrastructure_role": infrastructure_role,
        "project_role_prefix": f"arn:aws:iam::{account_id}:role/{name}-*",
        "repositories": [
            f"arn:aws:ecr:{REGION}:{account_id}:repository/{name}-{kind}"
            for kind in ("train", "eval", "serve")
        ],
        "api_collection": f"arn:aws:apigateway:{REGION}::/apis",
        "api_resources": f"arn:aws:apigateway:{REGION}::/apis*",
        "cloudfront_distribution": f"arn:aws:cloudfront::{account_id}:distribution/*",
        "cloudfront_function": f"arn:aws:cloudfront::{account_id}:function/{name}-spa-rewrite",
        "event_rules": [
            f"arn:aws:events:{REGION}:{account_id}:rule/{name}-sagemaker-processing-failure",
            f"arn:aws:events:{REGION}:{account_id}:rule/{name}-sagemaker-training-failure",
        ],
        # Both patterns remain project-name scoped while avoiding duplicated root/stream ARNs
        # that would push the externally managed boundary over AWS's 6,144-byte quota.
        "log_groups": [
            f"arn:aws:logs:{REGION}:{account_id}:log-group:/aws/*/{name}-*",
            f"arn:aws:logs:{REGION}:{account_id}:log-group:/aws/*/{name}-*:*",
        ],
        "notification_topic": f"arn:aws:sns:{REGION}:{account_id}:{name}-*",
    }


def _statement(
    sid: str,
    actions: list[str],
    resources: list[str],
    condition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "Sid": sid,
        "Effect": "Allow",
        "Action": sorted(actions),
        "Resource": resources,
    }
    if condition is not None:
        result["Condition"] = condition
    return result


def build_boundary(
    account_id: str, environment: Environment = DEFAULT_ENVIRONMENT
) -> dict[str, Any]:
    """Return one environment's immutable ceiling for Terraform-created roles."""
    arn = _arns(account_id, environment)
    request_tags = {
        "StringEquals": {
            "aws:RequestTag/Environment": arn["environment"],
            "aws:RequestTag/Project": PROJECT,
        }
    }
    resource_tags = {
        "StringEquals": {
            "aws:ResourceTag/Environment": arn["environment"],
            "aws:ResourceTag/Project": PROJECT,
        }
    }
    statements = [
        _statement(
            "StBkt",
            ["s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:ListBucket"],
            [arn["state_bucket"]],
        ),
        _statement(
            "StObj",
            ["s3:GetObject", "s3:PutObject"],
            [arn["state_object"], arn["financial_ledger"]],
        ),
        _statement(
            "StLock",
            ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"],
            [arn["state_lock"]],
        ),
        _statement(
            "Bkts",
            [
                "s3:AbortMultipartUpload",
                "s3:CreateBucket",
                "s3:DeleteBucket",
                "s3:DeleteObject",
                "s3:Get*",
                "s3:List*",
                "s3:Put*",
            ],
            [
                arn["artifact_bucket"],
                f"{arn['artifact_bucket']}/*",
                arn["site_bucket"],
                f"{arn['site_bucket']}/*",
            ],
        ),
        {
            "Sid": "DenyArtifactPolicy",
            "Effect": "Deny",
            "Action": ["s3:DeleteBucketPolicy", "s3:PutBucketPolicy"],
            "Resource": [arn["artifact_bucket"]],
        },
        _statement("EcrA", ["ecr:GetAuthorizationToken"], ["*"]),
        _statement(
            "Ecr",
            ["ecr:*"],
            arn["repositories"],
        ),
        _statement(
            "ApiR",
            ["apigateway:GET"],
            [arn["api_resources"]],
        ),
        _statement(
            "ApiC",
            ["apigateway:POST"],
            [arn["api_collection"]],
            request_tags,
        ),
        _statement(
            "ApiW",
            ["apigateway:PATCH", "apigateway:POST", "apigateway:PUT"],
            [arn["api_resources"]],
            resource_tags,
        ),
        _statement(
            "CfR",
            [
                "cloudfront:DescribeFunction",
                "cloudfront:GetCachePolicy",
                "cloudfront:GetDistribution",
                "cloudfront:GetDistributionConfig",
                "cloudfront:GetFunction",
                "cloudfront:GetOriginAccessControl",
                "cloudfront:GetOriginRequestPolicy",
                "cloudfront:GetResponseHeadersPolicy",
                "cloudfront:ListTagsForResource",
            ],
            ["*"],
        ),
        _statement(
            "CfCoreC",
            [
                "cloudfront:CreateOriginAccessControl",
                "cloudfront:CreateResponseHeadersPolicy",
            ],
            ["*"],
        ),
        _statement(
            "CfTagC",
            [
                "cloudfront:CreateDistribution",
                "cloudfront:CreateFunction",
                "cloudfront:TagResource",
            ],
            ["*"],
            request_tags,
        ),
        _statement(
            "CfTagW",
            [
                "cloudfront:CreateInvalidation",
                "cloudfront:PublishFunction",
                "cloudfront:TagResource",
                "cloudfront:UntagResource",
                "cloudfront:UpdateDistribution",
                "cloudfront:UpdateFunction",
            ],
            [arn["cloudfront_distribution"], arn["cloudfront_function"]],
            resource_tags,
        ),
        _statement(
            "Lambda",
            ["lambda:*"],
            [f"arn:aws:lambda:{REGION}:{account_id}:function:{arn['name']}-api*"],
        ),
        _statement(
            "Logs",
            ["logs:*"],
            arn["log_groups"],
        ),
        _statement(
            "LogList",
            ["logs:DescribeLogGroups"],
            ["*"],
        ),
        _statement(
            "Alarms",
            ["cloudwatch:*"],
            [f"arn:aws:cloudwatch:{REGION}:{account_id}:alarm:{arn['name']}-*"],
        ),
        _statement(
            "Events",
            ["events:*"],
            arn["event_rules"],
        ),
        _statement(
            "Sns",
            ["sns:*"],
            [arn["notification_topic"]],
        ),
        _statement(
            "SmJobs",
            ["sagemaker:*"],
            [
                f"arn:aws:sagemaker:{REGION}:{account_id}:processing-job/{arn['name']}-*",
                f"arn:aws:sagemaker:{REGION}:{account_id}:training-job/{arn['name']}-*",
            ],
        ),
        _statement(
            "P",
            ["pricing:GetProducts", "servicequotas:GetServiceQuota"],
            ["*"],
        ),
        _statement(
            "B",
            ["budgets:*"],
            [f"arn:aws:budgets::{account_id}:budget/{arn['name']}-*"],
        ),
        _statement(
            "ExecApi",
            ["execute-api:Invoke"],
            [f"arn:aws:execute-api:{REGION}:{account_id}:*/*/*/*"],
        ),
        _statement(
            "IR",
            [
                "iam:GetOpenIDConnectProvider",
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:ListAttachedRolePolicies",
                "iam:ListInstanceProfilesForRole",
                "iam:ListRolePolicies",
                "iam:ListRoleTags",
            ],
            [
                arn["project_role_prefix"],
                f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com",
            ],
        ),
        _statement(
            "PR",
            ["iam:PassRole"],
            arn["workload_roles"],
            {
                "StringEquals": {
                    "iam:PassedToService": ["lambda.amazonaws.com", "sagemaker.amazonaws.com"]
                }
            },
        ),
    ]
    # Boundary Sids do not affect authorization. Keep only the explicit-deny label
    # used by the attestation validator so enumerated project resources still fit
    # AWS's 6,144-character managed-policy ceiling.
    for statement in statements:
        if statement.get("Sid") != "DenyArtifactPolicy":
            statement.pop("Sid", None)
    document = {"Version": "2012-10-17", "Statement": statements}
    validate_boundary(document)
    return document


def build_state_policy(account_id: str, role_name: str = STATE_ROLE_NAME) -> dict[str, Any]:
    arn = _arns(account_id)
    bucket_actions = sorted(
        STATE_BUCKET_READ_ACTIONS
        | {
            "s3:CreateBucket",
            "s3:GetBucketLocation",
            "s3:GetBucketOwnershipControls",
            "s3:GetBucketPublicAccessBlock",
            "s3:GetBucketTagging",
            "s3:GetBucketVersioning",
            "s3:GetEncryptionConfiguration",
            "s3:GetLifecycleConfiguration",
            "s3:ListBucket",
            "s3:PutBucketOwnershipControls",
            "s3:PutBucketPublicAccessBlock",
            "s3:PutBucketTagging",
            "s3:PutBucketVersioning",
            "s3:PutEncryptionConfiguration",
            "s3:PutLifecycleConfiguration",
        }
    )
    document = {
        "Version": "2012-10-17",
        "Statement": [
            _statement("FixedStateBucketContract", bucket_actions, [arn["state_bucket"]]),
            _statement(
                "BootstrapStateObject",
                ["s3:GetObject", "s3:PutObject"],
                [arn["state_object"].replace("/prod/", "/bootstrap/")],
            ),
            _statement(
                "BootstrapLockObject",
                ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"],
                [arn["state_lock"].replace("/prod/", "/bootstrap/")],
            ),
            _statement(
                "ReadFinancialLedger",
                ["s3:GetObject"],
                [arn["financial_ledger"]],
            ),
            _statement(
                "CreateFinancialLedgerWithCas",
                ["s3:PutObject"],
                [arn["financial_ledger"]],
                {"StringEquals": {"s3:if-none-match": "*"}},
            ),
            _statement(
                "UpdateFinancialLedgerWithCas",
                ["s3:PutObject"],
                [arn["financial_ledger"]],
                {"Null": {"s3:if-match": "false"}},
            ),
            _statement(
                "SimulateOnlyThisBootstrapRole",
                ["iam:SimulatePrincipalPolicy"],
                [f"arn:aws:iam::{account_id}:role/{role_name}"],
            ),
            _statement(
                "AuditOnlyThisBootstrapRole",
                [
                    "iam:GetRole",
                    "iam:GetRolePolicy",
                    "iam:ListAttachedRolePolicies",
                    "iam:ListRolePolicies",
                ],
                [f"arn:aws:iam::{account_id}:role/{role_name}"],
            ),
        ],
    }
    validate_state_policy(document)
    return document


def build_platform_seed_policy(
    account_id: str, environment: Environment = DEFAULT_ENVIRONMENT
) -> dict[str, Any]:
    """Return the exact temporary authority for first apply and protected identity changes."""
    arn = _arns(account_id, environment)
    target_roles = arn["roles"]
    create_condition = {"StringEquals": {"iam:PermissionsBoundary": arn["boundary"]}}
    request_tags = {
        "StringEquals": {
            "aws:RequestTag/Environment": arn["environment"],
            "aws:RequestTag/Project": PROJECT,
        }
    }
    resource_tags = {
        "StringEquals": {
            "aws:ResourceTag/Environment": arn["environment"],
            "aws:ResourceTag/Project": PROJECT,
        }
    }
    document = {
        "Version": "2012-10-17",
        "Statement": [
            _statement(
                "ListEnvironmentTerraformState",
                ["s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:ListBucket"],
                [arn["state_bucket"]],
            ),
            _statement(
                "EnvironmentTerraformState",
                ["s3:GetObject", "s3:PutObject"],
                [arn["state_object"], arn["financial_ledger"]],
            ),
            _statement(
                "EnvironmentTerraformLock",
                ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"],
                [arn["state_lock"]],
            ),
            _statement(
                "CreateOrBoundExactProjectRoles",
                ["iam:CreateRole", "iam:PutRolePermissionsBoundary"],
                target_roles,
                create_condition,
            ),
            _statement(
                "ManageOnlyProjectRoleDefinitions",
                [
                    "iam:GetRole",
                    "iam:GetRolePolicy",
                    "iam:ListAttachedRolePolicies",
                    "iam:ListInstanceProfilesForRole",
                    "iam:ListRolePolicies",
                    "iam:ListRoleTags",
                    "iam:PutRolePolicy",
                    "iam:TagRole",
                    "iam:UntagRole",
                    "iam:UpdateAssumeRolePolicy",
                    "iam:UpdateRole",
                    "iam:UpdateRoleDescription",
                ],
                target_roles,
            ),
            _statement(
                "AuditOnlyThisSeedRole",
                [
                    "iam:GetRole",
                    "iam:GetRolePolicy",
                    "iam:ListAttachedRolePolicies",
                    "iam:ListRolePolicies",
                ],
                [arn["seed_role"]],
            ),
            _statement(
                "AuditOnlyEnvironmentBoundary",
                ["iam:GetPolicy", "iam:GetPolicyVersion"],
                [arn["boundary"]],
            ),
            _statement(
                "ReadExistingGithubProvider",
                ["iam:GetOpenIDConnectProvider"],
                [f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com"],
            ),
            _statement(
                "PassOnlyBoundedWorkloadRoles",
                ["iam:PassRole"],
                arn["workload_roles"],
                {
                    "StringEquals": {
                        "iam:PassedToService": [
                            "lambda.amazonaws.com",
                            "sagemaker.amazonaws.com",
                        ]
                    }
                },
            ),
            _statement(
                "CreateBaseProjectBuckets",
                [
                    "s3:CreateBucket",
                    "s3:GetAccelerateConfiguration",
                    "s3:GetBucketAcl",
                    "s3:GetBucketCORS",
                    "s3:GetBucketLogging",
                    "s3:GetBucketLocation",
                    "s3:GetBucketObjectLockConfiguration",
                    "s3:GetBucketOwnershipControls",
                    "s3:GetBucketPolicy",
                    "s3:GetBucketPublicAccessBlock",
                    "s3:GetBucketRequestPayment",
                    "s3:GetBucketTagging",
                    "s3:GetBucketVersioning",
                    "s3:GetBucketWebsite",
                    "s3:GetEncryptionConfiguration",
                    "s3:GetLifecycleConfiguration",
                    "s3:GetReplicationConfiguration",
                    "s3:ListBucket",
                    "s3:PutBucketOwnershipControls",
                    "s3:PutBucketPublicAccessBlock",
                    "s3:PutBucketTagging",
                    "s3:PutBucketVersioning",
                    "s3:PutEncryptionConfiguration",
                    "s3:PutLifecycleConfiguration",
                    "s3:TagResource",
                ],
                [arn["artifact_bucket"], arn["site_bucket"]],
            ),
            _statement(
                "CreateBaseProjectRepositories",
                [
                    "ecr:CreateRepository",
                    "ecr:DescribeRepositories",
                    "ecr:GetLifecyclePolicy",
                    "ecr:GetLifecyclePolicyPreview",
                    "ecr:GetRepositoryPolicy",
                    "ecr:ListTagsForResource",
                    "ecr:PutImageScanningConfiguration",
                    "ecr:PutImageTagMutability",
                    "ecr:PutLifecyclePolicy",
                    "ecr:SetRepositoryPolicy",
                    "ecr:TagResource",
                    "ecr:UntagResource",
                ],
                arn["repositories"],
            ),
            _statement(
                "ReadApiGatewayInventory",
                ["apigateway:GET"],
                [arn["api_resources"]],
            ),
            _statement(
                "CreateTaggedProjectApis",
                ["apigateway:POST"],
                [arn["api_collection"]],
                request_tags,
            ),
            _statement(
                "ReconcileTaggedProjectApis",
                ["apigateway:PATCH", "apigateway:POST", "apigateway:PUT"],
                [arn["api_resources"]],
                resource_tags,
            ),
            _statement(
                "ReadCloudFrontInventory",
                [
                    "cloudfront:DescribeFunction",
                    "cloudfront:GetCachePolicy",
                    "cloudfront:GetDistribution",
                    "cloudfront:GetDistributionConfig",
                    "cloudfront:GetFunction",
                    "cloudfront:GetOriginAccessControl",
                    "cloudfront:GetOriginRequestPolicy",
                    "cloudfront:GetResponseHeadersPolicy",
                    "cloudfront:ListTagsForResource",
                ],
                ["*"],
            ),
            _statement(
                "CreateUntaggedCloudFrontPrimitives",
                [
                    "cloudfront:CreateOriginAccessControl",
                    "cloudfront:CreateResponseHeadersPolicy",
                ],
                ["*"],
            ),
            _statement(
                "CreateTaggedCloudFrontResources",
                [
                    "cloudfront:CreateDistribution",
                    "cloudfront:CreateFunction",
                    "cloudfront:TagResource",
                ],
                ["*"],
                request_tags,
            ),
            _statement(
                "ReconcileTaggedCloudFront",
                [
                    "cloudfront:CreateInvalidation",
                    "cloudfront:PublishFunction",
                    "cloudfront:TagResource",
                    "cloudfront:UntagResource",
                    "cloudfront:UpdateDistribution",
                    "cloudfront:UpdateFunction",
                ],
                [arn["cloudfront_distribution"], arn["cloudfront_function"]],
                resource_tags,
            ),
            _statement(
                "ReconcileNamedLambdaFunction",
                ["lambda:*"],
                [f"arn:aws:lambda:{REGION}:{account_id}:function:{arn['name']}-api*"],
            ),
            _statement(
                "ReadLogAndAlarmInventory",
                ["cloudwatch:DescribeAlarms", "logs:DescribeLogGroups"],
                ["*"],
            ),
            _statement(
                "ReconcileExactLogGroups",
                [
                    "logs:CreateLogGroup",
                    "logs:DescribeMetricFilters",
                    "logs:ListTagsForResource",
                    "logs:PutMetricFilter",
                    "logs:PutRetentionPolicy",
                    "logs:TagResource",
                    "logs:UntagResource",
                ],
                arn["log_groups"],
            ),
            _statement(
                "ReconcileProjectAlarms",
                ["cloudwatch:*"],
                [f"arn:aws:cloudwatch:{REGION}:{account_id}:alarm:{arn['name']}-*"],
            ),
            _statement(
                "ReconcileProjectEvents",
                [
                    "events:DescribeRule",
                    "events:ListTagsForResource",
                    "events:ListTargetsByRule",
                    "events:PutRule",
                    "events:PutTargets",
                    "events:TagResource",
                    "events:UntagResource",
                ],
                arn["event_rules"],
            ),
            _statement(
                "ReconcileProjectNotificationTopic",
                [
                    "sns:CreateTopic",
                    "sns:GetSubscriptionAttributes",
                    "sns:GetTopicAttributes",
                    "sns:ListSubscriptionsByTopic",
                    "sns:ListTagsForResource",
                    "sns:SetTopicAttributes",
                    "sns:Subscribe",
                    "sns:TagResource",
                    "sns:UntagResource",
                ],
                [arn["notification_topic"]],
            ),
            _statement(
                "Budget",
                ["budgets:*"],
                [f"arn:aws:budgets::{account_id}:budget/{arn['name']}-*"],
            ),
        ],
    }
    validate_seed_policy(document, account_id, environment)
    return document


def build_trust(
    account_id: str,
    owner: str,
    owner_id: str,
    repository_id: str,
    purpose: TrustPurpose = "platform-seed",
) -> dict[str, Any]:
    _validate_identity(account_id, owner, owner_id, repository_id)
    if purpose == "platform-seed":
        github_environment = "aws-infrastructure"
        workflow_file = "infrastructure.yml"
    elif purpose == "state-bootstrap":
        github_environment = "aws-state-bootstrap"
        workflow_file = "bootstrap-infrastructure.yml"
    else:
        raise ValueError("trust purpose is invalid")
    provider = f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com"
    immutable_subject = (
        f"repo:{owner}@{owner_id}/{REPOSITORY_NAME}@{repository_id}:"
        f"environment:{github_environment}:job_workflow_ref:{owner}/{REPOSITORY_NAME}/"
        f".github/workflows/{workflow_file}@refs/heads/main"
    )
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ExactRepositoryEnvironmentOidc",
                "Effect": "Allow",
                "Principal": {"Federated": provider},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:ref": "refs/heads/main",
                        "token.actions.githubusercontent.com:repository": f"{owner}/{REPOSITORY_NAME}",
                        "token.actions.githubusercontent.com:repository_id": repository_id,
                        "token.actions.githubusercontent.com:repository_owner_id": owner_id,
                        "token.actions.githubusercontent.com:sub": immutable_subject,
                    }
                },
            }
        ],
    }
    if len(json.dumps(document, separators=(",", ":"), sort_keys=True)) > 2048:
        raise ValueError("trust policy exceeds AWS's default 2,048-character quota")
    return document


def _actions(document: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for statement in document["Statement"]:
        value = statement["Action"]
        result.update([value] if isinstance(value, str) else value)
    return result


def validate_boundary(document: dict[str, Any]) -> None:
    actions = _actions(document)
    wildcards = {action for action in actions if "*" in action}
    if "*" in actions or wildcards - APPROVED_BOUNDARY_WILDCARDS:
        raise ValueError("boundary contains an unapproved wildcard action")
    iam_actions = {action for action in actions if action.startswith("iam:")}
    if iam_actions - {
        "iam:GetOpenIDConnectProvider",
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "iam:ListRolePolicies",
        "iam:ListRoleTags",
        "iam:PassRole",
    }:
        raise ValueError("boundary contains an unapproved IAM action")
    mutation_actions = {
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:PutRolePolicy",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
        "iam:UpdateRole",
        "iam:UpdateRoleDescription",
    }
    if actions.intersection(mutation_actions):
        raise ValueError("boundary must not permit role, trust, or inline-policy mutation")
    deny = next(
        (
            statement
            for statement in document["Statement"]
            if statement.get("Sid") == "DenyArtifactPolicy"
        ),
        None,
    )
    if (
        deny is None
        or deny["Effect"] != "Deny"
        or set(deny["Action"]) != {"s3:DeleteBucketPolicy", "s3:PutBucketPolicy"}
        or len(deny["Resource"]) != 1
        or not deny["Resource"][0].endswith("-artifacts")
    ):
        raise ValueError("boundary must explicitly deny artifact bucket-policy mutation")
    serialized = json.dumps(document, separators=(",", ":"), sort_keys=True)
    if len(serialized) > 6144:
        raise ValueError("boundary exceeds AWS's 6,144-character managed-policy limit")


def validate_state_policy(document: dict[str, Any]) -> None:
    actions = _actions(document)
    missing = STATE_BUCKET_READ_ACTIONS - actions
    if missing:
        raise ValueError(f"state policy is missing provider refresh reads: {sorted(missing)}")
    if "iam:SimulatePrincipalPolicy" not in actions:
        raise ValueError("state policy cannot support the pre-create authorization proof")
    if actions & {"s3:DeleteBucket", "iam:PassRole", "iam:PutRolePolicy"}:
        raise ValueError("state policy exceeds the fixed state-bootstrap authority")
    if len(json.dumps(document, separators=(",", ":"), sort_keys=True)) > 10240:
        raise ValueError("state inline policy exceeds AWS's 10,240-character role quota")


def validate_seed_policy(
    document: dict[str, Any],
    account_id: str,
    environment: Environment = DEFAULT_ENVIRONMENT,
) -> None:
    arn = _arns(account_id, environment)
    serialized = json.dumps(document, sort_keys=True)
    seed_arn = arn["seed_role"]
    self_statements = [
        statement for statement in document["Statement"] if seed_arn in statement["Resource"]
    ]
    if len(self_statements) != 1 or self_statements[0]["Sid"] != "AuditOnlyThisSeedRole":
        raise ValueError("seed role may reference itself only in its exact audit statement")
    self_actions = set(self_statements[0]["Action"])
    if self_actions != {
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
    }:
        raise ValueError("seed role self-reference must remain read-only")
    if arn["boundary"] not in serialized:
        raise ValueError("seed role creation must require the external boundary")
    if any(
        action in _actions(document)
        for action in ("iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion")
    ):
        raise ValueError("seed role must not be able to mutate the boundary policy")
    if _actions(document).intersection({"s3:DeleteBucketPolicy", "s3:PutBucketPolicy"}):
        raise ValueError("seed role must not mutate project bucket policies")
    observability_mutations = {
        action
        for action in _actions(document)
        if action.startswith(("events:", "logs:", "sns:"))
        and action
        not in {
            "events:DescribeRule",
            "events:ListTagsForResource",
            "events:ListTargetsByRule",
            "logs:DescribeLogGroups",
            "logs:DescribeMetricFilters",
            "logs:ListTagsForResource",
            "sns:GetSubscriptionAttributes",
            "sns:GetTopicAttributes",
            "sns:ListSubscriptionsByTopic",
            "sns:ListTagsForResource",
        }
    }
    for statement in document["Statement"]:
        statement_actions = set(
            [statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"]
        )
        if "*" in statement["Resource"] and statement_actions.intersection(observability_mutations):
            raise ValueError("seed observability mutations must target exact project resources")
    if len(json.dumps(document, separators=(",", ":"), sort_keys=True)) > 10240:
        raise ValueError("seed inline policy exceeds AWS's 10,240-character role quota")


def render_document(
    kind: DocumentKind,
    account_id: str,
    owner: str,
    owner_id: str,
    repository_id: str,
    environment: Environment = DEFAULT_ENVIRONMENT,
    trust_purpose: TrustPurpose = "platform-seed",
) -> dict[str, Any]:
    _validate_identity(account_id, owner, owner_id, repository_id)
    if kind == "boundary":
        return build_boundary(account_id, environment)
    if kind == "platform-seed-policy":
        return build_platform_seed_policy(account_id, environment)
    if kind == "state-policy":
        return build_state_policy(account_id)
    return build_trust(account_id, owner, owner_id, repository_id, trust_purpose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        required=True,
        choices=("boundary", "platform-seed-policy", "state-policy", "trust"),
    )
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--repository-owner", required=True)
    parser.add_argument("--repository-owner-id", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--environment", choices=("dev", "prod"), default="prod")
    parser.add_argument(
        "--trust-purpose",
        choices=("platform-seed", "state-bootstrap"),
        default="platform-seed",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    document = render_document(
        cast(DocumentKind, args.kind),
        args.account_id,
        args.repository_owner,
        args.repository_owner_id,
        args.repository_id,
        cast(Environment, args.environment),
        cast(TrustPurpose, args.trust_purpose),
    )
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(text, end="")
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
