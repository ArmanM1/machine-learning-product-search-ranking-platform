output "artifact_bucket_name" {
  value = module.platform.artifact_bucket_name
}

output "site_bucket_name" {
  value = module.platform.site_bucket_name
}

output "ecr_repository_urls" {
  value = module.platform.ecr_repository_urls
}

output "sagemaker_training_role_arn" {
  value = module.platform.sagemaker_training_role_arn
}

output "sagemaker_processing_role_arn" {
  value = module.platform.sagemaker_processing_role_arn
}

output "github_deployment_role_arn" {
  value = module.platform.github_deployment_role_arn
}

output "github_workflow_role_arns" {
  value = module.platform.github_workflow_role_arns
}

output "lambda_function_name" {
  value = module.platform.lambda_function_name
}

output "candidate_api_url" {
  value = module.platform.candidate_api_url
}

output "production_api_url" {
  value = module.platform.production_api_url
}

output "cloudfront_distribution_id" {
  value = module.platform.cloudfront_distribution_id
}

output "cloudfront_url" {
  value = module.platform.cloudfront_url
}

output "cost_guard" {
  value = module.platform.cost_guard
}
