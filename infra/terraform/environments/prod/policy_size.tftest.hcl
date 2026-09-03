provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}

run "production_inline_policy_fits_aws_role_quota" {
  command = plan

  variables {
    owner_alias                       = "project-owner"
    github_repository                 = "example/machine-learning-product-search-ranking-platform"
    github_repository_owner_id        = "123456"
    github_repository_id              = "654321"
    create_github_oidc_provider       = false
    existing_github_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    enable_budgets                    = false
    enable_serving                    = false
    enable_public_serving             = false
  }

  override_data {
    target = module.platform.data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:root"
      id         = "123456789012"
      user_id    = "123456789012"
    }
  }

  override_data {
    target = module.platform.data.aws_partition.current
    values = {
      partition          = "aws"
      dns_suffix         = "amazonaws.com"
      reverse_dns_prefix = "com.amazonaws"
    }
  }

  assert {
    condition     = output.github_production_inline_policy_character_count <= 10000
    error_message = "The rendered production inline policy exceeds the 10,000-character engineering budget below AWS's 10,240-character role quota."
  }
}
