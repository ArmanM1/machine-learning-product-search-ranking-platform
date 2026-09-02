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
  name               = "${local.name}-sagemaker-training"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume_role.json
  tags               = local.common_tags
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
  name               = "${local.name}-sagemaker-processing"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume_role.json
  tags               = local.common_tags
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
        "public/*",
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
      "${aws_s3_bucket.artifacts.arn}/public/*",
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
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
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
      values   = ["repo:${var.github_repository}:environment:production"]
    }
  }
}

resource "aws_iam_role" "github_deployment" {
  name                 = "${local.name}-github-production"
  assume_role_policy   = data.aws_iam_policy_document.github_assume_role.json
  max_session_duration = 3600
  tags                 = local.common_tags
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
      values   = ["repo:${var.github_repository}:environment:${each.key}"]
    }
  }
}

resource "aws_iam_role" "github_workflow" {
  for_each = local.nonproduction_github_environments

  name                 = "${local.name}-github-${each.key}"
  assume_role_policy   = data.aws_iam_policy_document.github_workflow_assume_role[each.key].json
  max_session_duration = 3600
  tags                 = local.common_tags
}

data "aws_iam_policy_document" "github_deployment" {
  statement {
    sid       = "PriceAndIdentityRead"
    effect    = "Allow"
    actions   = ["pricing:GetProducts"]
    resources = ["*"]
  }

  statement {
    sid    = "LocateVersionedArtifactAndSiteBuckets"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      aws_s3_bucket.site.arn,
    ]
  }

  statement {
    sid    = "ListOnlyDeploymentPrefixes"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      aws_s3_bucket.site.arn,
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
    sid    = "ReadProjectArtifacts"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/promoted/*",
      "${aws_s3_bucket.artifacts.arn}/public/*",
    ]
  }

  statement {
    sid    = "WriteControlledArtifactPrefixes"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/promoted/current.json",
      "${aws_s3_bucket.artifacts.arn}/public/*",
    ]
  }

  statement {
    sid    = "ManageStaticReleaseObjects"
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
      "${aws_s3_bucket.site.arn}/*",
    ]
  }

  statement {
    sid       = "EcrLogin"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ProjectImageManagement"
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
    resources = [aws_ecr_repository.images["serve"].arn]
  }

  statement {
    sid     = "PassOnlyProjectWorkloadRoles"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.lambda.arn,
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
    sid    = "VersionedLambdaRelease"
    effect = "Allow"
    actions = [
      "lambda:GetAlias",
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:GetProvisionedConcurrencyConfig",
      "lambda:ListAliases",
      "lambda:ListVersionsByFunction",
      "lambda:PublishVersion",
      "lambda:UpdateAlias",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
    ]
    resources = ["arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api*"]
  }

  statement {
    sid       = "InvalidateOneDistribution"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetDistribution"]
    resources = ["arn:${local.partition}:cloudfront::${local.account_id}:distribution/*"]
  }

  statement {
    sid       = "InvokeCandidateSmokeApi"
    effect    = "Allow"
    actions   = ["execute-api:Invoke"]
    resources = ["arn:${local.partition}:execute-api:${var.aws_region}:${local.account_id}:*/*/*/*"]
  }

  statement {
    sid       = "ReadProjectLogs"
    effect    = "Allow"
    actions   = ["logs:GetLogEvents", "logs:FilterLogEvents"]
    resources = ["arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/*/${local.name}-*:*"]
  }
}

resource "aws_iam_role_policy" "github_deployment" {
  name   = "project-release-operations"
  role   = aws_iam_role.github_deployment.id
  policy = data.aws_iam_policy_document.github_deployment.json
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
    sid       = "ReadCurrentPricing"
    effect    = "Allow"
    actions   = ["pricing:GetProducts"]
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
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/runs/*/baseline-summary.json",
      "${aws_s3_bucket.artifacts.arn}/runs/*/curated-queries.json",
      "${aws_s3_bucket.artifacts.arn}/runs/*/manifest.json",
      "${aws_s3_bucket.artifacts.arn}/runs/*/summary.json",
      "${aws_s3_bucket.artifacts.arn}/promoted/current.json",
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
  statement {
    sid    = "UseOnlyProjectTerraformState"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:PutObject",
    ]
    resources = [
      "arn:${local.partition}:s3:::${local.state_bucket_name}",
      "arn:${local.partition}:s3:::${local.state_bucket_name}/${var.project_name}/*",
    ]
  }

  statement {
    sid    = "ReadProjectIdentityConfiguration"
    effect = "Allow"
    actions = [
      "iam:GetOpenIDConnectProvider",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
    ]
    resources = concat(
      [
        aws_iam_role.sagemaker_training.arn,
        aws_iam_role.sagemaker_processing.arn,
        aws_iam_role.lambda.arn,
        aws_iam_role.github_deployment.arn,
      ],
      values(aws_iam_role.github_workflow)[*].arn,
      var.create_github_oidc_provider ? [aws_iam_openid_connect_provider.github[0].arn] : [var.existing_github_oidc_provider_arn],
    )
  }

  statement {
    sid    = "ManageOnlyProjectRolesAndInlinePolicies"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:DeleteRolePolicy",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
    ]
    resources = concat(
      [
        aws_iam_role.sagemaker_training.arn,
        aws_iam_role.sagemaker_processing.arn,
        aws_iam_role.lambda.arn,
        aws_iam_role.github_deployment.arn,
      ],
      values(aws_iam_role.github_workflow)[*].arn,
    )
  }

  dynamic "statement" {
    for_each = var.create_github_oidc_provider ? [1] : []
    content {
      sid    = "ManageProjectCreatedGithubOidcProvider"
      effect = "Allow"
      actions = [
        "iam:AddClientIDToOpenIDConnectProvider",
        "iam:CreateOpenIDConnectProvider",
        "iam:DeleteOpenIDConnectProvider",
        "iam:RemoveClientIDFromOpenIDConnectProvider",
        "iam:TagOpenIDConnectProvider",
        "iam:UntagOpenIDConnectProvider",
        "iam:UpdateOpenIDConnectProviderThumbprint",
      ]
      resources = [aws_iam_openid_connect_provider.github[0].arn]
    }
  }

  statement {
    sid    = "ManageProjectBuckets"
    effect = "Allow"
    actions = [
      "s3:DeleteBucketPolicy",
      "s3:DeleteBucket",
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
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      aws_s3_bucket.site.arn,
    ]
  }

  statement {
    sid    = "ManageProjectRepositoryConfiguration"
    effect = "Allow"
    actions = [
      "ecr:DeleteLifecyclePolicy",
      "ecr:DeleteRepositoryPolicy",
      "ecr:DeleteRepository",
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
    resources = values(aws_ecr_repository.images)[*].arn
  }

  statement {
    sid    = "ManageProjectApiGateway"
    effect = "Allow"
    actions = [
      "apigateway:DELETE",
      "apigateway:GET",
      "apigateway:PATCH",
      "apigateway:POST",
      "apigateway:PUT",
    ]
    resources = ["arn:${local.partition}:apigateway:${var.aws_region}::/apis*"]
  }

  statement {
    sid    = "ManageProjectCloudFront"
    effect = "Allow"
    actions = [
      "cloudfront:CreateFunction",
      "cloudfront:CreateDistribution",
      "cloudfront:CreateOriginAccessControl",
      "cloudfront:CreateResponseHeadersPolicy",
      "cloudfront:DeleteFunction",
      "cloudfront:DeleteDistribution",
      "cloudfront:DeleteOriginAccessControl",
      "cloudfront:DeleteResponseHeadersPolicy",
      "cloudfront:GetCachePolicy",
      "cloudfront:GetDistribution",
      "cloudfront:GetDistributionConfig",
      "cloudfront:GetFunction",
      "cloudfront:GetOriginAccessControl",
      "cloudfront:GetOriginRequestPolicy",
      "cloudfront:GetResponseHeadersPolicy",
      "cloudfront:DescribeFunction",
      "cloudfront:ListTagsForResource",
      "cloudfront:PublishFunction",
      "cloudfront:TagResource",
      "cloudfront:UpdateDistribution",
      "cloudfront:UpdateFunction",
      "cloudfront:UpdateOriginAccessControl",
      "cloudfront:UpdateResponseHeadersPolicy",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManageNamedLambdaFunction"
    effect = "Allow"
    actions = [
      "lambda:AddPermission",
      "lambda:CreateAlias",
      "lambda:CreateFunction",
      "lambda:DeleteAlias",
      "lambda:DeleteFunction",
      "lambda:DeleteFunctionConcurrency",
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
      "lambda:RemovePermission",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:UpdateAlias",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
    ]
    resources = ["arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api*"]
  }

  statement {
    sid     = "PassOnlyProjectWorkloadRolesDuringReconciliation"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.sagemaker_training.arn,
      aws_iam_role.sagemaker_processing.arn,
      aws_iam_role.lambda.arn,
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
    sid    = "ManageObservability"
    effect = "Allow"
    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource",
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
      "events:DeleteRule",
      "events:DescribeRule",
      "events:ListTagsForResource",
      "events:ListTargetsByRule",
      "events:PutRule",
      "events:PutTargets",
      "events:RemoveTargets",
      "events:TagResource",
      "events:UntagResource",
      "logs:CreateLogGroup",
      "logs:DeleteLogGroup",
      "logs:DeleteMetricFilter",
      "logs:DescribeLogGroups",
      "logs:DescribeMetricFilters",
      "logs:ListTagsForResource",
      "logs:PutMetricFilter",
      "logs:PutRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",
      "sns:GetSubscriptionAttributes",
      "sns:GetTopicAttributes",
      "sns:CreateTopic",
      "sns:DeleteTopic",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:TagResource",
      "sns:Unsubscribe",
      "sns:UntagResource",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManageApprovedBudgets"
    effect = "Allow"
    actions = [
      "budgets:CreateBudget",
      "budgets:CreateNotification",
      "budgets:CreateSubscriber",
      "budgets:DeleteBudget",
      "budgets:DeleteNotification",
      "budgets:DeleteSubscriber",
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
  for_each = {
    aws-infrastructure = aws_iam_role.github_workflow["aws-infrastructure"].id
    production         = aws_iam_role.github_deployment.id
  }

  name   = "project-terraform-reconciliation"
  role   = each.value
  policy = data.aws_iam_policy_document.github_terraform.json
}
