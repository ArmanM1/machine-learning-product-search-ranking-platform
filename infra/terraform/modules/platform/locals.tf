data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  name       = "${var.project_name}-${var.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    Owner       = var.owner_alias
    ManagedBy   = "terraform"
    CostCenter  = var.project_name
  }

  artifact_bucket_name = "${local.name}-${local.account_id}-${var.aws_region}-artifacts"
  site_bucket_name     = "${local.name}-${local.account_id}-${var.aws_region}-site"
  state_bucket_name    = "${var.project_name}-terraform-state-${local.account_id}-${var.aws_region}"
  artifact_bucket_arn  = "arn:${local.partition}:s3:::${local.artifact_bucket_name}"
  site_bucket_arn      = "arn:${local.partition}:s3:::${local.site_bucket_name}"
  image_repository_arns = {
    for workload in local.image_repositories : workload =>
    "arn:${local.partition}:ecr:${var.aws_region}:${local.account_id}:repository/${local.name}-${workload}"
  }
  sagemaker_training_role_arn   = "arn:${local.partition}:iam::${local.account_id}:role/${local.name}-sagemaker-training"
  sagemaker_processing_role_arn = "arn:${local.partition}:iam::${local.account_id}:role/${local.name}-sagemaker-processing"
  lambda_role_arn               = "arn:${local.partition}:iam::${local.account_id}:role/${local.name}-lambda"
  budget_kill_switch_role_arn   = "arn:${local.partition}:iam::${local.account_id}:role/${local.name}-budget-kill-switch"
  github_deployment_role_arn    = "arn:${local.partition}:iam::${local.account_id}:role/${local.name}-github-production"
  github_workflow_role_arns = {
    for github_environment in setsubtract(var.github_environments, toset(["production"])) : github_environment =>
    "arn:${local.partition}:iam::${local.account_id}:role/${local.name}-github-${github_environment}"
  }
  project_log_group_arns = [
    "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/apigateway/${local.name}-candidate",
    "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/apigateway/${local.name}-production",
    "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/lambda/${local.name}-api",
    "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/lambda/${local.name}-api-budget-kill-switch",
  ]
  project_log_resource_arns = flatten([
    for log_group_arn in local.project_log_group_arns : [log_group_arn, "${log_group_arn}:*"]
  ])
  project_event_rule_arns = [
    "arn:${local.partition}:events:${var.aws_region}:${local.account_id}:rule/${local.name}-sagemaker-processing-failure",
    "arn:${local.partition}:events:${var.aws_region}:${local.account_id}:rule/${local.name}-sagemaker-training-failure",
  ]
  project_alarm_arns = [
    "arn:${local.partition}:cloudwatch:${var.aws_region}:${local.account_id}:alarm:${local.name}-api-5xx",
    "arn:${local.partition}:cloudwatch:${var.aws_region}:${local.account_id}:alarm:${local.name}-concurrency-bound",
    "arn:${local.partition}:cloudwatch:${var.aws_region}:${local.account_id}:alarm:${local.name}-model-load-failure",
  ]
  notification_topic_arn       = "arn:${local.partition}:sns:${var.aws_region}:${local.account_id}:${local.name}-operations"
  budget_kill_switch_topic_arn = "arn:${local.partition}:sns:${var.aws_region}:${local.account_id}:${local.name}-budget-kill-switch"
  # This maximum-permissions policy is created by the external identity bootstrap and is
  # intentionally not a Terraform resource in this module.
  project_permissions_boundary_arn = "arn:${local.partition}:iam::${local.account_id}:policy/${var.project_name}-${var.environment}-permissions-boundary"

  github_repository_owner         = split("/", var.github_repository)[0]
  github_repository_name          = split("/", var.github_repository)[1]
  github_immutable_subject_prefix = "repo:${local.github_repository_owner}@${var.github_repository_owner_id}/${local.github_repository_name}@${var.github_repository_id}"
  github_environment_workflow_files = {
    aws-baseline         = "baseline.yml"
    aws-data             = "prepare-data.yml"
    aws-images           = "build-images.yml"
    aws-infrastructure   = "infrastructure.yml"
    aws-training         = "train.yml"
    aws-trial-selection  = "freeze-trial-selection.yml"
    baseline-release     = "bootstrap-baseline.yml"
    heldout-release      = "release.yml"
    production           = "deploy.yml"
    production-benchmark = "benchmark-serving.yml"
  }
  github_oidc_provider_arn = "arn:${local.partition}:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"

  # Only the presence bit is safe to declassify for count/for_each; the address remains sensitive.
  alarm_notifications_enabled = nonsensitive(var.alarm_notification_email != "")
  alarm_actions               = local.alarm_notifications_enabled ? [aws_sns_topic.operations[0].arn] : []
}
