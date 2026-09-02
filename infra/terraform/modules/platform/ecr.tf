locals {
  image_repositories = toset(["train", "eval", "serve"])
}

resource "aws_ecr_repository" "images" {
  for_each = local.image_repositories

  name                 = "${local.name}-${each.key}"
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "train_eval" {
  for_each = toset(["train", "eval"])

  repository = aws_ecr_repository.images[each.key].name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove untagged layers quickly"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 2
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Bound immutable job images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }
        action = { type = "expire" }
      },
    ]
  })
}

resource "aws_ecr_lifecycle_policy" "serve" {
  repository = aws_ecr_repository.images["serve"].name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove untagged layers quickly"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 2
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Retain promoted release and one rollback release"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["release-"]
          countType     = "imageCountMoreThan"
          countNumber   = 2
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 3
        description  = "Retain promoted model and one rollback model"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["model-"]
          countType     = "imageCountMoreThan"
          countNumber   = 2
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 4
        description  = "Bound non-release build images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = { type = "expire" }
      },
    ]
  })
}

data "aws_iam_policy_document" "lambda_ecr" {
  statement {
    sid    = "LambdaPullOnly"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api*"]
    }
  }
}

resource "aws_ecr_repository_policy" "serve" {
  repository = aws_ecr_repository.images["serve"].name
  policy     = data.aws_iam_policy_document.lambda_ecr.json
}
