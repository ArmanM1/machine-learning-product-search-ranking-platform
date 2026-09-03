variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "product-search-ranking"
}

variable "owner_alias" {
  type = string
}

variable "github_repository" {
  type        = string
  description = "Exact GitHub repository in owner/name form."

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/machine-learning-product-search-ranking-platform$", var.github_repository))
    error_message = "github_repository must be the exact owner/machine-learning-product-search-ranking-platform pair."
  }
}

variable "github_repository_owner_id" {
  type        = string
  description = "Immutable decimal GitHub database ID for the repository owner."

  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be a positive decimal GitHub database ID with at most 20 digits."
  }
}

variable "github_repository_id" {
  type        = string
  description = "Immutable decimal GitHub database ID for the repository."

  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.github_repository_id))
    error_message = "github_repository_id must be a positive decimal GitHub database ID with at most 20 digits."
  }
}

variable "github_environments" {
  type = set(string)
  default = [
    "aws-baseline",
    "aws-data",
    "aws-images",
    "aws-infrastructure",
    "aws-training",
    "aws-trial-selection",
    "baseline-release",
    "heldout-release",
    "production",
    "production-benchmark",
  ]
}

variable "create_github_oidc_provider" {
  type    = bool
  default = false
}

variable "existing_github_oidc_provider_arn" {
  type    = string
  default = ""
}

variable "enable_budgets" {
  type    = bool
  default = false
}

variable "budget_notification_email" {
  type      = string
  default   = ""
  sensitive = true
}

variable "enable_serving" {
  type    = bool
  default = false
}

variable "enable_public_serving" {
  type    = bool
  default = false

  validation {
    condition     = !var.enable_public_serving || var.enable_serving
    error_message = "enable_public_serving requires enable_serving=true."
  }
}

variable "serving_image_uri" {
  type    = string
  default = ""
}

variable "serving_git_sha" {
  type    = string
  default = ""
}

variable "serving_deployment_nonce" {
  type    = string
  default = ""
}

variable "alarm_notification_email" {
  type      = string
  default   = ""
  sensitive = true
}
