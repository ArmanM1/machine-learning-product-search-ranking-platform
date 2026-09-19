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
    enable_public_serving_kill_switch = false
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

  assert {
    condition     = output.github_infrastructure_inline_policy_character_count <= 10000
    error_message = "The rendered infrastructure inline policy exceeds the 10,000-character engineering budget below AWS's 10,240-character role quota."
  }
}

run "public_serving_does_not_implicitly_enable_kill_switch" {
  command = plan

  variables {
    owner_alias                       = "project-owner"
    github_repository                 = "example/machine-learning-product-search-ranking-platform"
    github_repository_owner_id        = "123456"
    github_repository_id              = "654321"
    create_github_oidc_provider       = false
    existing_github_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    enable_budgets                    = false
    enable_serving                    = true
    enable_public_serving             = true
    enable_public_serving_kill_switch = false
    serving_image_uri                 = "123456789012.dkr.ecr.us-east-1.amazonaws.com/product-search-ranking-serve@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    serving_git_sha                   = "0000000000000000000000000000000000000000"
    serving_deployment_nonce          = "1-1-release-test"
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
    condition     = output.budget_kill_switch.status == "disabled"
    error_message = "Public serving must not implicitly arm the optional kill switch."
  }

  assert {
    condition = (
      output.budget_kill_switch.automatic_expiry_hours == null &&
      output.budget_kill_switch.expiry_rule_arn == null &&
      output.budget_kill_switch.handler_function_name == null &&
      output.budget_kill_switch.handler_execution_role_arn == null &&
      output.budget_kill_switch.topic_arn == null
    )
    error_message = "Kill-switch IAM, Lambda, SNS, and EventBridge resources must remain absent unless explicitly enabled."
  }

  assert {
    condition     = output.cost_guard.public_serving_expiry_hours == null
    error_message = "Disabled automatic expiry must be represented as null, not as an active 24-hour control."
  }
}

run "public_serving_kill_switch_requires_explicit_opt_in" {
  command = plan

  variables {
    owner_alias                       = "project-owner"
    github_repository                 = "example/machine-learning-product-search-ranking-platform"
    github_repository_owner_id        = "123456"
    github_repository_id              = "654321"
    create_github_oidc_provider       = false
    existing_github_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    enable_budgets                    = false
    enable_serving                    = true
    enable_public_serving             = true
    enable_public_serving_kill_switch = true
    serving_image_uri                 = "123456789012.dkr.ecr.us-east-1.amazonaws.com/product-search-ranking-serve@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    serving_git_sha                   = "0000000000000000000000000000000000000000"
    serving_deployment_nonce          = "1-1-release-test"
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
    condition     = output.budget_kill_switch.status == "armed"
    error_message = "The public-serving kill switch must arm only after explicit opt-in."
  }

  assert {
    condition     = output.budget_kill_switch.automatic_expiry_hours == 24
    error_message = "Explicit kill-switch opt-in must expose the 24-hour expiry contract."
  }
}
