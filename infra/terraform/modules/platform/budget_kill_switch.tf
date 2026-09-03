locals {
  budget_kill_switch_threshold_usd = 10
  budget_kill_switch_topic_enabled = var.environment == "prod" && var.enable_budgets
  public_serving_expiry_hours      = 24
  budget_kill_switch_enabled       = var.environment == "prod" && var.enable_public_serving
}

resource "aws_sns_topic" "budget_kill_switch" {
  count = local.budget_kill_switch_topic_enabled ? 1 : 0

  name = "${local.name}-budget-kill-switch"
  tags = local.common_tags
}

data "aws_iam_policy_document" "budget_kill_switch_topic" {
  count = local.budget_kill_switch_topic_enabled ? 1 : 0

  statement {
    sid       = "AllowOnlyAccountBudgetsToPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.budget_kill_switch[0].arn]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    # AWS Budgets documents this account-bound source-ARN shape for SNS delivery.
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:budgets::${local.account_id}:*"]
    }
  }
}

resource "aws_sns_topic_policy" "budget_kill_switch" {
  count = local.budget_kill_switch_topic_enabled ? 1 : 0

  arn    = aws_sns_topic.budget_kill_switch[0].arn
  policy = data.aws_iam_policy_document.budget_kill_switch_topic[0].json
}

# The role exists in production before public serving is enabled. This lets the restricted
# production reconciler pass it to the event-driven function without gaining IAM mutation rights.
resource "aws_iam_role" "budget_kill_switch" {
  count = local.budget_kill_switch_enabled ? 1 : 0

  name                 = "${local.name}-budget-kill-switch"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume_role.json
  permissions_boundary = local.project_permissions_boundary_arn
  tags                 = local.common_tags
}

data "aws_iam_policy_document" "budget_kill_switch" {
  count = local.budget_kill_switch_enabled ? 1 : 0

  statement {
    sid    = "WriteOnlyKillSwitchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/lambda/${local.name}-api-budget-kill-switch:*",
    ]
  }

  statement {
    sid    = "StopOnlyPublicRanker"
    effect = "Allow"
    actions = [
      "lambda:GetFunctionConcurrency",
      "lambda:PutFunctionConcurrency",
    ]
    resources = [
      "arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.name}-api",
    ]
  }

  statement {
    sid    = "DisableOnlyPublicSiteDistribution"
    effect = "Allow"
    actions = [
      "cloudfront:GetDistributionConfig",
      "cloudfront:UpdateDistribution",
    ]
    resources = [aws_cloudfront_distribution.site[0].arn]
  }
}

resource "aws_iam_role_policy" "budget_kill_switch" {
  count = local.budget_kill_switch_enabled ? 1 : 0

  name   = "stop-only-public-ranker-and-site"
  role   = aws_iam_role.budget_kill_switch[0].id
  policy = data.aws_iam_policy_document.budget_kill_switch[0].json
}

resource "aws_cloudwatch_log_group" "budget_kill_switch" {
  count = local.budget_kill_switch_enabled ? 1 : 0

  name              = "/aws/lambda/${local.name}-api-budget-kill-switch"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.common_tags
}

resource "aws_lambda_function" "budget_kill_switch" {
  count = local.budget_kill_switch_enabled ? 1 : 0

  function_name = "${local.name}-api-budget-kill-switch"
  role          = aws_iam_role.budget_kill_switch[0].arn
  package_type  = "Image"
  image_uri     = var.serving_image_uri
  architectures = ["x86_64"]
  memory_size   = 128
  timeout       = 30

  image_config {
    command = ["search_rank.serving.budget_kill_switch.handler"]
  }

  environment {
    variables = {
      BUDGET_SNS_TOPIC_ARN       = try(aws_sns_topic.budget_kill_switch[0].arn, "")
      CLOUDFRONT_DISTRIBUTION_ID = aws_cloudfront_distribution.site[0].id
      EXPIRY_EVENT_RULE_ARN      = aws_cloudwatch_event_rule.public_serving_expiry[0].arn
      RANKER_FUNCTION_NAME       = aws_lambda_function.api[0].function_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.budget_kill_switch]
  tags       = local.common_tags
}

resource "aws_lambda_permission" "budget_kill_switch_sns" {
  count = local.budget_kill_switch_enabled && local.budget_kill_switch_topic_enabled ? 1 : 0

  statement_id   = "AllowOnlyBudgetKillSwitchTopic"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.budget_kill_switch[0].function_name
  principal      = "sns.amazonaws.com"
  source_arn     = aws_sns_topic.budget_kill_switch[0].arn
  source_account = local.account_id
}

resource "aws_sns_topic_subscription" "budget_kill_switch" {
  count = local.budget_kill_switch_enabled && local.budget_kill_switch_topic_enabled ? 1 : 0

  topic_arn = aws_sns_topic.budget_kill_switch[0].arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.budget_kill_switch[0].arn

  depends_on = [aws_lambda_permission.budget_kill_switch_sns]
}

# This schedule is the primary budget-independent public exposure bound. EventBridge incurs no
# idle compute; its first invocation arrives within the maximum 24-hour public window and every
# subsequent invocation keeps the controls fail-closed until explicit operator recovery.
resource "aws_cloudwatch_event_rule" "public_serving_expiry" {
  count = local.budget_kill_switch_enabled ? 1 : 0

  name                = "${local.name}-public-serving-expiry"
  description         = "Disable public serving no later than 24 hours after it is enabled"
  schedule_expression = "rate(${local.public_serving_expiry_hours} hours)"
  state               = "ENABLED"
  tags                = local.common_tags
}

resource "aws_cloudwatch_event_target" "public_serving_expiry" {
  count = local.budget_kill_switch_enabled ? 1 : 0

  rule      = aws_cloudwatch_event_rule.public_serving_expiry[0].name
  target_id = "public-serving-kill-switch"
  arn       = aws_lambda_function.budget_kill_switch[0].arn
}

resource "aws_lambda_permission" "public_serving_expiry" {
  count = local.budget_kill_switch_enabled ? 1 : 0

  statement_id   = "AllowOnlyPublicServingExpiryRule"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.budget_kill_switch[0].function_name
  principal      = "events.amazonaws.com"
  source_arn     = aws_cloudwatch_event_rule.public_serving_expiry[0].arn
  source_account = local.account_id
}
