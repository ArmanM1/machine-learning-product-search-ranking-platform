output "artifact_bucket_name" {
  description = "Private, versioned data/model/report artifact bucket."
  value       = aws_s3_bucket.artifacts.id
}

output "site_bucket_name" {
  description = "Private static-site origin bucket."
  value       = aws_s3_bucket.site.id
}

output "ecr_repository_urls" {
  description = "Immutable train/eval/serve repository URLs."
  value       = { for key, repository in aws_ecr_repository.images : key => repository.repository_url }
}

output "sagemaker_training_role_arn" {
  value = aws_iam_role.sagemaker_training.arn
}

output "sagemaker_processing_role_arn" {
  value = aws_iam_role.sagemaker_processing.arn
}

output "lambda_execution_role_arn" {
  value = aws_iam_role.lambda.arn
}

output "github_deployment_role_arn" {
  description = "Production-only GitHub OIDC role ARN retained for backwards-compatible automation wiring."
  value       = aws_iam_role.github_deployment.arn
}

output "github_production_inline_policy_character_count" {
  description = "Rendered aggregate character count for the production role single inline policy."
  value       = length(data.aws_iam_policy_document.github_production.minified_json)
}

output "github_infrastructure_inline_policy_character_count" {
  description = "Rendered aggregate character count for the infrastructure role single inline policy."
  value       = length(data.aws_iam_policy_document.github_terraform.minified_json)
}

output "github_workflow_role_arns" {
  description = "One repository-and-environment-bound GitHub OIDC role ARN per protected workflow environment."
  value = merge(
    { production = aws_iam_role.github_deployment.arn },
    { for environment, role in aws_iam_role.github_workflow : environment => role.arn },
  )
}

output "github_baseline_role_arn" {
  value = aws_iam_role.github_workflow["aws-baseline"].arn
}

output "github_trial_selection_role_arn" {
  value = aws_iam_role.github_workflow["aws-trial-selection"].arn
}

output "github_benchmark_role_arn" {
  value = aws_iam_role.github_workflow["production-benchmark"].arn
}

output "project_permissions_boundary_arn" {
  description = "Externally managed maximum-permissions boundary required on every project role."
  value       = local.project_permissions_boundary_arn
}

output "lambda_function_name" {
  value = try(aws_lambda_function.api[0].function_name, null)
}

output "candidate_api_url" {
  value = try(aws_apigatewayv2_stage.candidate[0].invoke_url, null)
}

output "production_api_url" {
  value = try(aws_apigatewayv2_stage.production[0].invoke_url, null)
}

output "cloudfront_distribution_id" {
  value = try(aws_cloudfront_distribution.site[0].id, null)
}

output "cloudfront_url" {
  value = try("https://${aws_cloudfront_distribution.site[0].domain_name}", null)
}

output "budget_kill_switch" {
  description = "Backward-compatible evidence for the budget-independent public expiry and optional AWS Budget trigger."
  value = {
    status = (
      local.budget_kill_switch_enabled ? "armed" : "disabled"
    )
    threshold_usd              = local.budget_kill_switch_threshold_usd
    trigger_types              = ["ACTUAL", "FORECASTED"]
    budget_trigger_enabled     = local.budget_kill_switch_topic_enabled
    automatic_expiry_hours     = local.public_serving_expiry_hours
    expiry_rule_arn            = try(aws_cloudwatch_event_rule.public_serving_expiry[0].arn, null)
    topic_arn                  = try(aws_sns_topic.budget_kill_switch[0].arn, null)
    handler_function_name      = try(aws_lambda_function.budget_kill_switch[0].function_name, null)
    handler_execution_role_arn = try(aws_iam_role.budget_kill_switch[0].arn, null)
    target_function_name       = try(aws_lambda_function.api[0].function_name, null)
    target_distribution_id     = try(aws_cloudfront_distribution.site[0].id, null)
    no_idle_compute            = true
    automatic_restore          = false
  }
}

output "cost_guard" {
  description = "Manual cost bounds plus the budget-independent production expiry and optional budget trigger."
  value = {
    campaign_budget_usd          = var.campaign_budget_usd
    maximum_out_of_pocket_usd    = var.maximum_out_of_pocket_usd
    required_credit_reserve_usd  = var.required_credit_reserve_usd
    budgets_enabled              = var.enable_budgets
    provisioned_concurrency      = 0
    lambda_reserved_concurrency  = var.lambda_reserved_concurrency
    sagemaker_realtime_endpoints = 0
    budget_kill_switch_armed     = local.budget_kill_switch_enabled
    budget_kill_switch_usd       = local.budget_kill_switch_threshold_usd
    public_serving_expiry_hours  = local.public_serving_expiry_hours
  }
}
