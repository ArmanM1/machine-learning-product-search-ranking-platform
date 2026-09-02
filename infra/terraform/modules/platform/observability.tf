resource "aws_sns_topic" "operations" {
  count = var.alarm_notification_email == "" ? 0 : 1

  name = "${local.name}-operations"
  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "sagemaker_training" {
  count = var.environment == "prod" ? 1 : 0

  name              = "/aws/sagemaker/TrainingJobs"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "sagemaker_processing" {
  count = var.environment == "prod" ? 1 : 0

  name              = "/aws/sagemaker/ProcessingJobs"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.common_tags
}

resource "aws_sns_topic_subscription" "operations_email" {
  count = var.alarm_notification_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.operations[0].arn
  protocol  = "email"
  endpoint  = var.alarm_notification_email
}

resource "aws_cloudwatch_log_metric_filter" "model_load_failure" {
  count = var.enable_serving ? 1 : 0

  name           = "${local.name}-model-load-failure"
  pattern        = "{ $.error_code = \"MODEL_LOAD_FAILED\" }"
  log_group_name = aws_cloudwatch_log_group.lambda.name

  metric_transformation {
    name      = "ModelLoadFailure"
    namespace = "ProductSearchRanking/${var.environment}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "model_load_failure" {
  count = var.enable_serving ? 1 : 0

  alarm_name          = "${local.name}-model-load-failure"
  alarm_description   = "A released model failed readiness during cold start."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.model_load_failure[0].metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.model_load_failure[0].metric_transformation[0].namespace
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "api_server_errors" {
  count = var.enable_serving ? 1 : 0

  alarm_name          = "${local.name}-api-5xx"
  alarm_description   = "Repeated public API server errors."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "5xx"
  namespace           = "AWS/ApiGateway"
  period              = 60
  statistic           = "Sum"
  threshold           = 3
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    ApiId = aws_apigatewayv2_api.production[0].id
    Stage = aws_apigatewayv2_stage.production[0].name
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "concurrency_bound" {
  count = var.enable_serving ? 1 : 0

  alarm_name          = "${local.name}-concurrency-bound"
  alarm_description   = "Inference reached its reserved concurrency bound of two."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "ConcurrentExecutions"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Maximum"
  threshold           = var.lambda_reserved_concurrency
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    FunctionName = aws_lambda_function.api[0].function_name
  }

  tags = local.common_tags
}

locals {
  sagemaker_failure_events = var.alarm_notification_email == "" ? {} : {
    training = {
      detail_type = "SageMaker Training Job State Change"
      status_key  = "TrainingJobStatus"
      name_key    = "TrainingJobName"
    }
    processing = {
      detail_type = "SageMaker Processing Job State Change"
      status_key  = "ProcessingJobStatus"
      name_key    = "ProcessingJobName"
    }
  }
}

resource "aws_cloudwatch_event_rule" "sagemaker_failure" {
  for_each = local.sagemaker_failure_events

  name        = "${local.name}-sagemaker-${each.key}-failure"
  description = "Project SageMaker ${each.key} job entered Failed or Stopped state."
  event_pattern = jsonencode({
    source        = ["aws.sagemaker"]
    "detail-type" = [each.value.detail_type]
    detail = {
      (each.value.status_key) = ["Failed", "Stopped"]
      (each.value.name_key)   = [{ prefix = "${local.name}-" }]
    }
  })
  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "sagemaker_failure" {
  for_each = local.sagemaker_failure_events

  rule = aws_cloudwatch_event_rule.sagemaker_failure[each.key].name
  arn  = aws_sns_topic.operations[0].arn
}

data "aws_iam_policy_document" "sns_events" {
  count = var.alarm_notification_email == "" ? 0 : 1

  statement {
    effect  = "Allow"
    actions = ["sns:Publish"]
    resources = [
      aws_sns_topic.operations[0].arn,
    ]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = values(aws_cloudwatch_event_rule.sagemaker_failure)[*].arn
    }
  }
}

resource "aws_sns_topic_policy" "operations" {
  count = var.alarm_notification_email == "" ? 0 : 1

  arn    = aws_sns_topic.operations[0].arn
  policy = data.aws_iam_policy_document.sns_events[0].json
}
