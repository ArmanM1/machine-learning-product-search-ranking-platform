data "aws_iam_policy_document" "sagemaker_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker_training" {
  name                 = "${local.name}-sagemaker-training"
  assume_role_policy   = data.aws_iam_policy_document.sagemaker_assume_role.json
  permissions_boundary = local.project_permissions_boundary_arn
  tags                 = local.common_tags
}

data "aws_iam_policy_document" "sagemaker_training" {
  statement {
    sid       = "LocateArtifactBucket"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid     = "ListOnlyTrainingPrefixes"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = [
      aws_s3_bucket.artifacts.arn,
    ]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "base-models/*",
        "runs/*/config/*",
        "runs/*/checkpoints/*",
        "runs/*/metrics/*",
        "runs/*/output/*",
        "runs/*/training-input/*",
      ]
    }
  }

  statement {
    sid    = "ReadPreparedDataAndBaseModels"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/base-models/*",
      "${aws_s3_bucket.artifacts.arn}/runs/*/checkpoints/*",
      "${aws_s3_bucket.artifacts.arn}/runs/*/config/*",
      "${aws_s3_bucket.artifacts.arn}/runs/*/training-input/*",
    ]
  }

  statement {
    sid    = "WriteRunArtifacts"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/runs/*/checkpoints/*",
      "${aws_s3_bucket.artifacts.arn}/runs/*/metrics/*",
      "${aws_s3_bucket.artifacts.arn}/runs/*/output/*",
    ]
  }

  statement {
    sid       = "GetEcrAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullTrainingImage"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.images["train"].arn]
  }

  statement {
    sid    = "WriteOnlyTrainingJobLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/sagemaker/TrainingJobs*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceAccount"
      values   = [local.account_id]
    }
  }

}

resource "aws_iam_role_policy" "sagemaker_training" {
  name   = "least-privilege-training"
  role   = aws_iam_role.sagemaker_training.id
  policy = data.aws_iam_policy_document.sagemaker_training.json
}

resource "aws_iam_role" "sagemaker_processing" {
  name                 = "${local.name}-sagemaker-processing"
  assume_role_policy   = data.aws_iam_policy_document.sagemaker_assume_role.json
  permissions_boundary = local.project_permissions_boundary_arn
  tags                 = local.common_tags
}

data "aws_iam_policy_document" "sagemaker_processing" {
  statement {
    sid       = "LocateArtifactBucket"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid     = "ListEvaluationPrefixes"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = [
      aws_s3_bucket.artifacts.arn,
    ]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "data/processed/*",
        "runs/*",
        "promoted/*",
      ]
    }
  }

  statement {
    sid    = "ReadEvaluationInputs"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/data/processed/*",
      "${aws_s3_bucket.artifacts.arn}/runs/*",
      "${aws_s3_bucket.artifacts.arn}/promoted/*",
    ]
  }

  statement {
    sid    = "WriteEvaluationReportsOnly"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/runs/*/reports/*",
    ]
  }

  statement {
    sid       = "GetEcrAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullEvaluationImage"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.images["eval"].arn]
  }

  statement {
    sid    = "WriteOnlyProcessingJobLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/sagemaker/ProcessingJobs*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceAccount"
      values   = [local.account_id]
    }
  }

}

resource "aws_iam_role_policy" "sagemaker_processing" {
  name   = "least-privilege-processing"
  role   = aws_iam_role.sagemaker_processing.id
  policy = data.aws_iam_policy_document.sagemaker_processing.json
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name                 = "${local.name}-lambda"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume_role.json
  permissions_boundary = local.project_permissions_boundary_arn
  tags                 = local.common_tags
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid    = "WriteFunctionLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  statement {
    sid    = "ReadSanitizedPublicEvidence"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/public/*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "logs-and-public-evidence-only"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

data "tls_certificate" "github" {
  count = var.create_github_oidc_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github[0].certificates[length(data.tls_certificate.github[0].certificates) - 1].sha1_fingerprint]
  tags            = local.common_tags
}

data "aws_iam_policy_document" "github_assume_role" {
  statement {
    sid     = "RepositoryAndEnvironmentBoundOidc"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_immutable_subject_prefix}:environment:production:workflow_ref:${var.github_repository}/.github/workflows/${local.github_environment_workflow_files["production"]}@refs/heads/main"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository_id"
      values   = [var.github_repository_id]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository"
      values   = [var.github_repository]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository_owner_id"
      values   = [var.github_repository_owner_id]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:ref"
      values   = ["refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deployment" {
  name                 = "${local.name}-github-production"
  assume_role_policy   = data.aws_iam_policy_document.github_assume_role.json
  max_session_duration = 3600
  permissions_boundary = local.project_permissions_boundary_arn
  tags                 = local.common_tags

  lifecycle {
    precondition {
      condition = (
        var.create_github_oidc_provider ||
        var.existing_github_oidc_provider_arn == local.github_oidc_provider_arn
      )
      error_message = "The existing GitHub OIDC provider must belong to this exact AWS account."
    }
  }
}

locals {
  nonproduction_github_environments = setsubtract(var.github_environments, toset(["production"]))
}

data "aws_iam_policy_document" "github_workflow_assume_role" {
  for_each = local.nonproduction_github_environments

  statement {
    sid     = "RepositoryAndSingleEnvironmentBoundOidc"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_immutable_subject_prefix}:environment:${each.key}:workflow_ref:${var.github_repository}/.github/workflows/${local.github_environment_workflow_files[each.key]}@refs/heads/main"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository_id"
      values   = [var.github_repository_id]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository"
      values   = [var.github_repository]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository_owner_id"
      values   = [var.github_repository_owner_id]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:ref"
      values   = ["refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_workflow" {
  for_each = local.nonproduction_github_environments

  name                 = "${local.name}-github-${each.key}"
  assume_role_policy   = data.aws_iam_policy_document.github_workflow_assume_role[each.key].json
  max_session_duration = 3600
  permissions_boundary = local.project_permissions_boundary_arn
  tags                 = local.common_tags
}

# Every AWS-mutating workflow receives only GetObject plus conditional PutObject on the one
# private campaign ledger. The If-Match/If-None-Match conditions prevent a workflow from
# bypassing the compare-and-swap protocol even if its application code is modified.
data "aws_iam_policy_document" "github_financial_ledger" {
  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}/cost-control/ledger.json"]
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}/cost-control/ledger.json"]

    condition {
      test     = "StringEquals"
      variable = "s3:if-none-match"
      values   = ["*"]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}/cost-control/ledger.json"]

    condition {
      test     = "Null"
      variable = "s3:if-match"
      values   = ["false"]
    }
  }
}

locals {
  # Production and aws-infrastructure receive this document through their consolidated
  # policies so each quota-sensitive role has one aggregate-size-checked inline policy.
  github_financial_ledger_roles = {
    for environment, role in aws_iam_role.github_workflow : environment => role.id
    if environment != "aws-infrastructure"
  }
}

resource "aws_iam_role_policy" "github_financial_ledger" {
  for_each = local.github_financial_ledger_roles

  name   = "atomic-financial-ledger-only"
  role   = each.value
  policy = data.aws_iam_policy_document.github_financial_ledger.minified_json
}

data "aws_iam_policy_document" "github_deployment" {
  statement {
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
    ]
    resources = [
      local.artifact_bucket_arn,
      local.site_bucket_arn,
    ]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "",
        "promoted/*",
        "public/*",
        "releases/*",
      ]
    }
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${local.artifact_bucket_arn}/promoted/*",
      "${local.artifact_bucket_arn}/public/*",
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${local.artifact_bucket_arn}/promoted/current.json",
      "${local.artifact_bucket_arn}/public/*",
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${local.site_bucket_arn}/*",
    ]
  }

  statement {
    effect    = "Deny"
    actions   = ["s3:DeleteObject"]
    resources = ["${local.site_bucket_arn}/releases/*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [local.image_repository_arns["serve"]]
  }

  statement {
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      local.lambda_role_arn,
      local.budget_kill_switch_role_arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values = [
        "lambda.amazonaws.com",
      ]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["execute-api:Invoke"]
    resources = ["arn:${local.partition}:execute-api:${var.aws_region}:${local.account_id}:*/*/*/*"]
  }
}

data "aws_iam_policy_document" "github_images" {
  statement {
    sid       = "EcrLogin"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PushOnlyProjectImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = values(aws_ecr_repository.images)[*].arn
  }
}

resource "aws_iam_role_policy" "github_images" {
  name   = "push-project-images-only"
  role   = aws_iam_role.github_workflow["aws-images"].id
  policy = data.aws_iam_policy_document.github_images.json
}

data "aws_iam_policy_document" "github_data" {
  statement {
    sid       = "LocateArtifactBucket"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid       = "ListOnlyPreparedDataAndPreparationEvidence"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "data/processed/*",
        "runs/data-preparation/*",
      ]
    }
  }

  statement {
    sid    = "ReadAndVerifyOnlyPreparedDataAndPreparationEvidence"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/data/processed/*",
      "${aws_s3_bucket.artifacts.arn}/runs/data-preparation/*",
    ]
  }

  statement {
    sid    = "PublishOnlyImmutablePreparedDataAndPreparationEvidence"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/data/processed/*",
      "${aws_s3_bucket.artifacts.arn}/runs/data-preparation/*",
    ]
  }
}

resource "aws_iam_role_policy" "github_data" {
  name   = "publish-content-addressed-prepared-data-only"
  role   = aws_iam_role.github_workflow["aws-data"].id
  policy = data.aws_iam_policy_document.github_data.json
}

data "aws_iam_policy_document" "github_training" {
  statement {
    sid       = "VerifyExactTrainingImageDigest"
    effect    = "Allow"
    actions   = ["ecr:DescribeImages"]
    resources = [aws_ecr_repository.images["train"].arn]
  }

  statement {
    sid       = "ReadCurrentPricing"
    effect    = "Allow"
    actions   = ["pricing:GetProducts"]
    resources = ["*"]
  }

  statement {
    sid       = "ReadManagedSpotTrainingQuota"
    effect    = "Allow"
    actions   = ["servicequotas:GetServiceQuota"]
    resources = ["*"]
  }

  statement {
    sid       = "LocateTrainingArtifactBucket"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid       = "ListOnlyTrainingRunArtifacts"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["runs/*"]
    }
  }

  statement {
    sid    = "ReadPreparedAndTrainingArtifacts"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/data/processed/*/artifact-checksums.json",
      "${aws_s3_bucket.artifacts.arn}/data/processed/*/manifest.json",
      "${aws_s3_bucket.artifacts.arn}/data/processed/*/train.parquet",
      "${aws_s3_bucket.artifacts.arn}/data/processed/*/validation.parquet",
      "${aws_s3_bucket.artifacts.arn}/runs/*",
    ]
  }

  statement {
    sid    = "WriteOnlyTrainingRunArtifacts"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/runs/*"]
  }

  statement {
    sid    = "SubmitOnlyProjectTrainingJobs"
    effect = "Allow"
    actions = [
      "sagemaker:AddTags",
      "sagemaker:CreateTrainingJob",
      "sagemaker:DescribeTrainingJob",
      "sagemaker:ListTags",
      "sagemaker:StopTrainingJob",
    ]
    resources = [
      "arn:${local.partition}:sagemaker:${var.aws_region}:${local.account_id}:training-job/${local.name}-*",
    ]
  }

  statement {
    sid       = "PassOnlyTrainingExecutionRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.sagemaker_training.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "github_training" {
  name   = "bounded-training-jobs-only"
  role   = aws_iam_role.github_workflow["aws-training"].id
  policy = data.aws_iam_policy_document.github_training.json
}

data "aws_iam_policy_document" "github_baseline" {
  statement {
    sid       = "LocateBaselineArtifactBucket"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid       = "ListOnlyValidationInputsAndBaselineRuns"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["data/processed/*", "runs/baseline-run-*/*"]
    }
  }

  statement {
    sid    = "ReadOnlyValidationInputs"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/data/processed/*/artifact-checksums.json",
      "${aws_s3_bucket.artifacts.arn}/data/processed/*/manifest.json",
      "${aws_s3_bucket.artifacts.arn}/data/processed/*/validation.parquet",
    ]
  }

  statement {
    sid    = "PublishOnlyValidationBaselineRuns"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/runs/baseline-run-*/*"]
  }
}

resource "aws_iam_role_policy" "github_baseline" {
  name   = "validation-baseline-runs-only"
  role   = aws_iam_role.github_workflow["aws-baseline"].id
  policy = data.aws_iam_policy_document.github_baseline.json
}

data "aws_iam_policy_document" "github_trial_selection" {
  statement {
    sid       = "LocateTrialArtifactBucket"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid       = "ListOnlyTrainingRunsAndTrialSelection"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["runs/*"]
    }
  }

  statement {
    sid    = "ReadOnlyTrainingDeclarationsAndArtifacts"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/runs/*"]
  }

  statement {
    sid    = "PublishOnlyImmutableTrialSelection"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/runs/trial-selection/trial-selection-*/*",
    ]
  }
}

resource "aws_iam_role_policy" "github_trial_selection" {
  name   = "validation-trial-selection-only"
  role   = aws_iam_role.github_workflow["aws-trial-selection"].id
  policy = data.aws_iam_policy_document.github_trial_selection.json
}

data "aws_iam_policy_document" "github_benchmark" {
  statement {
    sid    = "LocateBenchmarkArtifactBucket"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
    ]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid    = "ListOnlyBenchmarkEvidence"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["promoted/*", "public/*"]
    }
  }

  statement {
    sid    = "ReadOnlyPromotedAndDeploymentEvidence"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/promoted/*",
      "${aws_s3_bucket.artifacts.arn}/public/*/deployment-evidence.json",
    ]
  }

  statement {
    sid    = "PublishOnlyImmutablePerformanceEvidence"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/public/*/performance/runs/github-*-attempt-*/sha256-*/*",
    ]
  }

  statement {
    sid    = "ReadOnlyBoundedRankerConfiguration"
    effect = "Allow"
    actions = [
      "lambda:GetAlias",
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:GetFunctionConcurrency",
      "lambda:GetProvisionedConcurrencyConfig",
    ]
    resources = [
      "arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api",
      "arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api:*",
    ]
  }
}

resource "aws_iam_role_policy" "github_benchmark" {
  name   = "read-serving-publish-performance-only"
  role   = aws_iam_role.github_workflow["production-benchmark"].id
  policy = data.aws_iam_policy_document.github_benchmark.json
}

data "aws_iam_policy_document" "github_baseline_release" {
  statement {
    sid       = "VerifyEvaluationImageDigest"
    effect    = "Allow"
    actions   = ["ecr:DescribeImages"]
    resources = [aws_ecr_repository.images["eval"].arn]
  }

  statement {
    sid    = "LocateVersionedArtifactBucket"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
    ]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid    = "ListOnlyValidationEvidence"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "runs/*",
        "promoted/*",
      ]
    }
  }

  statement {
    sid    = "ReadOnlyValidationEvidenceAndInitialPointer"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectTagging",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/runs/*/baseline-summary.json",
      "${aws_s3_bucket.artifacts.arn}/runs/*/curated-queries.json",
      "${aws_s3_bucket.artifacts.arn}/runs/*/manifest.json",
      "${aws_s3_bucket.artifacts.arn}/runs/*/summary.json",
      "${aws_s3_bucket.artifacts.arn}/promoted/*",
    ]
  }

  statement {
    sid    = "PublishOnlyImmutableBaselineAndInitialPointer"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/promoted/*",
    ]
  }
}

resource "aws_iam_role_policy" "github_baseline_release" {
  name   = "validation-baseline-bootstrap-only"
  role   = aws_iam_role.github_workflow["baseline-release"].id
  policy = data.aws_iam_policy_document.github_baseline_release.json
}

data "aws_iam_policy_document" "github_heldout_release" {
  statement {
    sid       = "VerifyEvaluationImageDigest"
    effect    = "Allow"
    actions   = ["ecr:DescribeImages"]
    resources = [aws_ecr_repository.images["eval"].arn]
  }

  statement {
    sid       = "ReadCurrentPricing"
    effect    = "Allow"
    actions   = ["pricing:GetProducts"]
    resources = ["*"]
  }

  statement {
    sid       = "ReadProcessingJobQuota"
    effect    = "Allow"
    actions   = ["servicequotas:GetServiceQuota"]
    resources = ["*"]
  }

  statement {
    sid    = "LocateAndListReleaseArtifacts"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
      "s3:ListBucket",
      "s3:ListBucketVersions",
    ]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid    = "ReadFrozenReleaseInputs"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/data/processed/*/manifest.json",
      "${aws_s3_bucket.artifacts.arn}/runs/*",
      "${aws_s3_bucket.artifacts.arn}/promoted/*",
    ]
  }

  statement {
    sid    = "WriteCountedReportsAndPromotion"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/heldout/access-counter.json",
      "${aws_s3_bucket.artifacts.arn}/promoted/*",
      "${aws_s3_bucket.artifacts.arn}/public/*",
      "${aws_s3_bucket.artifacts.arn}/runs/*",
    ]
  }

  statement {
    sid    = "SubmitOnlyProjectProcessingJobs"
    effect = "Allow"
    actions = [
      "sagemaker:AddTags",
      "sagemaker:CreateProcessingJob",
      "sagemaker:DescribeProcessingJob",
      "sagemaker:ListTags",
      "sagemaker:StopProcessingJob",
    ]
    resources = [
      "arn:${local.partition}:sagemaker:${var.aws_region}:${local.account_id}:processing-job/${local.name}-*",
    ]
  }

  statement {
    sid       = "PassOnlyProcessingExecutionRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.sagemaker_processing.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "github_heldout_release" {
  name   = "counted-heldout-release-only"
  role   = aws_iam_role.github_workflow["heldout-release"].id
  policy = data.aws_iam_policy_document.github_heldout_release.json
}

data "aws_iam_policy_document" "github_terraform" {
  source_policy_documents = [data.aws_iam_policy_document.github_financial_ledger.minified_json]

  statement {
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
      "s3:ListBucket",
    ]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}"]

    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values = [
        "${var.project_name}/prod/terraform.tfstate",
        "${var.project_name}/prod/terraform.tfstate.tflock",
      ]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}/${var.project_name}/prod/terraform.tfstate"]
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}/${var.project_name}/prod/terraform.tfstate.tflock"]
  }

  statement {
    effect = "Allow"
    actions = [
      "iam:GetOpenIDConnectProvider",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
    ]
    resources = concat(
      [
        local.sagemaker_training_role_arn,
        local.sagemaker_processing_role_arn,
        local.lambda_role_arn,
        local.budget_kill_switch_role_arn,
        local.github_deployment_role_arn,
      ],
      values(local.github_workflow_role_arns),
      [local.github_oidc_provider_arn],
    )
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:CreateBucket",
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetLifecycleConfiguration",
      "s3:GetBucketLogging",
      "s3:GetBucketObjectLockConfiguration",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketRequestPayment",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetBucketWebsite",
      "s3:GetEncryptionConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:PutLifecycleConfiguration",
      "s3:PutBucketOwnershipControls",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
    ]
    resources = [
      local.artifact_bucket_arn,
      local.site_bucket_arn,
    ]
  }

  statement {
    effect = "Allow"
    actions = [
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
    ]
    resources = values(local.image_repository_arns)
  }

  statement {
    effect    = "Allow"
    actions   = ["apigateway:GET"]
    resources = ["arn:${local.partition}:apigateway:${var.aws_region}::/apis*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["apigateway:POST"]
    resources = ["arn:${local.partition}:apigateway:${var.aws_region}::/apis"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["apigateway:PATCH", "apigateway:POST", "apigateway:PUT"]
    resources = ["arn:${local.partition}:apigateway:${var.aws_region}::/apis*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    effect = "Allow"
    actions = [
      "cloudfront:DescribeFunction",
      "cloudfront:GetCachePolicy",
      "cloudfront:GetDistribution",
      "cloudfront:GetDistributionConfig",
      "cloudfront:GetFunction",
      "cloudfront:GetOriginAccessControl",
      "cloudfront:GetOriginRequestPolicy",
      "cloudfront:GetResponseHeadersPolicy",
      "cloudfront:ListTagsForResource",
    ]
    resources = ["*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateOriginAccessControl", "cloudfront:CreateResponseHeadersPolicy"]
    resources = ["*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateDistribution", "cloudfront:CreateFunction", "cloudfront:TagResource"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    effect = "Allow"
    actions = [
      "cloudfront:CreateInvalidation",
      "cloudfront:PublishFunction",
      "cloudfront:TagResource",
      "cloudfront:UntagResource",
      "cloudfront:UpdateDistribution",
      "cloudfront:UpdateFunction",
    ]
    resources = [
      "arn:${local.partition}:cloudfront::${local.account_id}:distribution/*",
      "arn:${local.partition}:cloudfront::${local.account_id}:function/${local.name}-spa-rewrite",
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    effect = "Allow"
    actions = [
      "lambda:AddPermission",
      "lambda:CreateAlias",
      "lambda:CreateFunction",
      "lambda:GetAlias",
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:GetPolicy",
      "lambda:GetFunctionConcurrency",
      "lambda:ListAliases",
      "lambda:ListVersionsByFunction",
      "lambda:ListTags",
      "lambda:PublishVersion",
      "lambda:PutFunctionConcurrency",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:UpdateAlias",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
    ]
    resources = ["arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api*"]
  }

  statement {
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      local.sagemaker_training_role_arn,
      local.sagemaker_processing_role_arn,
      local.lambda_role_arn,
      local.budget_kill_switch_role_arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values = [
        "lambda.amazonaws.com",
        "sagemaker.amazonaws.com",
      ]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudwatch:DescribeAlarms", "logs:DescribeLogGroups"]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "cloudwatch:ListTagsForResource",
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
    ]
    resources = local.project_alarm_arns
  }

  statement {
    effect = "Allow"
    actions = [
      "events:DescribeRule",
      "events:ListTagsForResource",
      "events:ListTargetsByRule",
      "events:PutRule",
      "events:PutTargets",
      "events:TagResource",
      "events:UntagResource",
    ]
    resources = local.project_event_rule_arns
  }

  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:DescribeMetricFilters",
      "logs:ListTagsForResource",
      "logs:PutMetricFilter",
      "logs:PutRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",
    ]
    resources = local.project_log_resource_arns
  }

  statement {
    effect = "Allow"
    actions = [
      "sns:CreateTopic",
      "sns:GetSubscriptionAttributes",
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:TagResource",
      "sns:UntagResource",
    ]
    resources = [
      local.notification_topic_arn,
      local.budget_kill_switch_topic_arn,
      "${local.budget_kill_switch_topic_arn}:*",
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "budgets:CreateBudget",
      "budgets:CreateNotification",
      "budgets:CreateSubscriber",
      "budgets:DescribeBudget",
      "budgets:DescribeNotificationsForBudget",
      "budgets:DescribeSubscribersForNotification",
      "budgets:ModifyBudget",
      "budgets:UpdateNotification",
      "budgets:UpdateSubscriber",
      "budgets:ViewBudget",
    ]
    resources = ["arn:${local.partition}:budgets::${local.account_id}:budget/${local.name}-*"]
  }
}

resource "aws_iam_role_policy" "github_terraform" {
  name   = "project-terraform-reconciliation"
  role   = aws_iam_role.github_workflow["aws-infrastructure"].id
  policy = data.aws_iam_policy_document.github_terraform.minified_json

  lifecycle {
    precondition {
      condition     = length(data.aws_iam_policy_document.github_terraform.minified_json) <= 10000
      error_message = "Infrastructure role aggregate inline policy exceeds the 10,000-character engineering budget below AWS's 10,240-character role quota."
    }
  }
}

# Production can refresh the complete Terraform state but can write only the serving
# surface. It receives no identity-creation, trust, boundary, or inline-policy mutation.
data "aws_iam_policy_document" "github_production_terraform" {
  statement {
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:ListBucket"]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}"]
    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values = [
        "${var.project_name}/prod/terraform.tfstate",
        "${var.project_name}/prod/terraform.tfstate.tflock",
      ]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}/${var.project_name}/prod/terraform.tfstate"]
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    resources = ["arn:${local.partition}:s3:::${local.state_bucket_name}/${var.project_name}/prod/terraform.tfstate.tflock"]
  }

  statement {
    effect = "Allow"
    actions = [
      "iam:GetOpenIDConnectProvider",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
    ]
    # Read-only refresh access follows the exact environment role namespace already
    # enforced by the external permissions boundary; identity mutation is absent.
    resources = [
      "arn:${local.partition}:iam::${local.account_id}:role/${local.name}-*",
      local.github_oidc_provider_arn,
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetBucketLocation",
      "s3:GetBucketLogging",
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
    ]
    resources = [local.artifact_bucket_arn, local.site_bucket_arn]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecr:DescribeRepositories",
      "ecr:GetLifecyclePolicy",
      "ecr:GetLifecyclePolicyPreview",
      "ecr:GetRepositoryPolicy",
      "ecr:ListTagsForResource",
    ]
    resources = values(local.image_repository_arns)
  }

  statement {
    effect = "Allow"
    actions = [
      "apigateway:GET",
      "cloudfront:DescribeFunction",
      "cloudfront:GetCachePolicy",
      "cloudfront:GetDistribution",
      "cloudfront:GetDistributionConfig",
      "cloudfront:GetFunction",
      "cloudfront:GetOriginAccessControl",
      "cloudfront:GetOriginRequestPolicy",
      "cloudfront:GetResponseHeadersPolicy",
      "cloudfront:ListTagsForResource",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource",
      "ecr:GetAuthorizationToken",
      "events:DescribeRule",
      "events:ListTagsForResource",
      "events:ListTargetsByRule",
      "lambda:GetFunctionConcurrency",
      "lambda:GetPolicy",
      "lambda:ListTags",
      "logs:DescribeLogGroups",
      "logs:DescribeMetricFilters",
      "logs:ListTagsForResource",
      "pricing:GetProducts",
      "sns:GetSubscriptionAttributes",
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
    ]
    resources = ["*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["budgets:DescribeBudget", "budgets:DescribeNotificationsForBudget", "budgets:DescribeSubscribersForNotification", "budgets:ViewBudget"]
    resources = ["arn:${local.partition}:budgets::${local.account_id}:budget/${local.name}-*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["apigateway:POST"]
    resources = ["arn:${local.partition}:apigateway:${var.aws_region}::/apis"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["apigateway:PATCH", "apigateway:POST", "apigateway:PUT"]
    resources = ["arn:${local.partition}:apigateway:${var.aws_region}::/apis*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateOriginAccessControl", "cloudfront:CreateResponseHeadersPolicy"]
    resources = ["*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateDistribution", "cloudfront:CreateFunction", "cloudfront:TagResource"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    effect  = "Allow"
    actions = ["cloudfront:CreateInvalidation", "cloudfront:PublishFunction", "cloudfront:TagResource", "cloudfront:UntagResource", "cloudfront:UpdateDistribution", "cloudfront:UpdateFunction"]
    resources = [
      "arn:${local.partition}:cloudfront::${local.account_id}:distribution/*",
      "arn:${local.partition}:cloudfront::${local.account_id}:function/${local.name}-spa-rewrite",
    ]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricAlarm", "cloudwatch:TagResource", "cloudwatch:UntagResource"]
    resources = ["arn:${local.partition}:cloudwatch:${var.aws_region}:${local.account_id}:alarm:${local.name}-*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "lambda:AddPermission",
      "lambda:CreateAlias",
      "lambda:CreateFunction",
      "lambda:GetAlias",
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:GetProvisionedConcurrencyConfig",
      "lambda:ListAliases",
      "lambda:ListVersionsByFunction",
      "lambda:PublishVersion",
      "lambda:PutFunctionConcurrency",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:UpdateAlias",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
    ]
    resources = ["arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "sns:GetSubscriptionAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:Subscribe",
    ]
    resources = [
      local.budget_kill_switch_topic_arn,
      "${local.budget_kill_switch_topic_arn}:*",
    ]
  }

  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:FilterLogEvents", "logs:GetLogEvents", "logs:PutMetricFilter", "logs:PutRetentionPolicy", "logs:TagResource", "logs:UntagResource"]
    resources = local.project_log_resource_arns
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:PutBucketPolicy"]
    resources = [local.site_bucket_arn]
  }

}

data "aws_iam_policy_document" "github_production" {
  source_policy_documents = [
    data.aws_iam_policy_document.github_deployment.minified_json,
    data.aws_iam_policy_document.github_financial_ledger.minified_json,
    data.aws_iam_policy_document.github_production_terraform.minified_json,
  ]
}

resource "aws_iam_role_policy" "github_deployment" {
  name   = "project-production-serving-only"
  role   = aws_iam_role.github_deployment.id
  policy = data.aws_iam_policy_document.github_production.minified_json

  lifecycle {
    precondition {
      condition     = length(data.aws_iam_policy_document.github_production.minified_json) <= 10240
      error_message = "Production role inline policy exceeds the AWS per-role character quota."
    }
  }
}
