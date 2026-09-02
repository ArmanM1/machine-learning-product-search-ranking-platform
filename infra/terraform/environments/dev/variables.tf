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
  type = string
}

variable "github_environments" {
  type = set(string)
  default = [
    "aws-data",
    "aws-images",
    "aws-infrastructure",
    "aws-training",
    "baseline-release",
    "heldout-release",
    "production",
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

variable "serving_image_uri" {
  type    = string
  default = ""
}

variable "alarm_notification_email" {
  type      = string
  default   = ""
  sensitive = true
}
