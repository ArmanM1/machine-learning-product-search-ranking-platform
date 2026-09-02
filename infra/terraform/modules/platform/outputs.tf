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

output "github_workflow_role_arns" {
  description = "One repository-and-environment-bound GitHub OIDC role ARN per protected workflow environment."
  value = merge(
    { production = aws_iam_role.github_deployment.arn },
    { for environment, role in aws_iam_role.github_workflow : environment => role.arn },
  )
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

output "cost_guard" {
  description = "Configuration values consumed by manual workflows; AWS Budgets are alerts, not hard stops."
  value = {
    campaign_budget_usd          = var.campaign_budget_usd
    maximum_out_of_pocket_usd    = var.maximum_out_of_pocket_usd
    required_credit_reserve_usd  = var.required_credit_reserve_usd
    budgets_enabled              = var.enable_budgets
    provisioned_concurrency      = 0
    lambda_reserved_concurrency  = var.lambda_reserved_concurrency
    sagemaker_realtime_endpoints = 0
  }
}
