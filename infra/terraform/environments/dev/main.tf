provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = "dev"
      Owner       = var.owner_alias
      ManagedBy   = "terraform"
    }
  }
}

module "platform" {
  source = "../../modules/platform"

  project_name                      = var.project_name
  environment                       = "dev"
  aws_region                        = var.aws_region
  owner_alias                       = var.owner_alias
  github_repository                 = var.github_repository
  github_repository_owner_id        = var.github_repository_owner_id
  github_repository_id              = var.github_repository_id
  github_environments               = var.github_environments
  create_github_oidc_provider       = var.create_github_oidc_provider
  existing_github_oidc_provider_arn = var.existing_github_oidc_provider_arn
  enable_budgets                    = var.enable_budgets
  budget_notification_email         = var.budget_notification_email
  maximum_out_of_pocket_usd         = 0
  required_credit_reserve_usd       = 40
  enable_serving                    = var.enable_serving
  enable_public_serving             = var.enable_public_serving
  serving_image_uri                 = var.serving_image_uri
  serving_git_sha                   = var.serving_git_sha
  serving_deployment_nonce          = var.serving_deployment_nonce
  alarm_notification_email          = var.alarm_notification_email
}
