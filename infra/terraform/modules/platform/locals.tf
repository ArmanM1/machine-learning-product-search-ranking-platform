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

  github_oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_github_oidc_provider_arn

  alarm_actions = var.alarm_notification_email == "" ? [] : [aws_sns_topic.operations[0].arn]
}
