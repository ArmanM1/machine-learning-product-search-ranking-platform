variable "project_name" {
  description = "Short lowercase project identifier used in names and tags."
  type        = string
  default     = "product-search-ranking"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.project_name))
    error_message = "project_name must be 3-32 lowercase letters, digits, or hyphens and start with a letter."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod."
  }
}

variable "aws_region" {
  description = "Single AWS region for the platform."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "This release is intentionally constrained to us-east-1. Record an ADR before changing it."
  }
}

variable "owner_alias" {
  description = "Non-sensitive owner alias used for cost-allocation tags."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{2,32}$", var.owner_alias))
    error_message = "owner_alias must be 2-32 non-sensitive letters, digits, dots, underscores, or hyphens."
  }
}

variable "github_repository" {
  description = "GitHub repository in owner/name form. Used to bind the OIDC trust policy."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/machine-learning-product-search-ranking-platform$", var.github_repository))
    error_message = "github_repository must be the exact owner/machine-learning-product-search-ranking-platform pair."
  }
}

variable "github_repository_owner_id" {
  description = "Immutable decimal GitHub database ID for the repository owner."
  type        = string

  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be a positive decimal GitHub database ID with at most 20 digits."
  }
}

variable "github_repository_id" {
  description = "Immutable decimal GitHub database ID for the repository."
  type        = string

  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.github_repository_id))
    error_message = "github_repository_id must be a positive decimal GitHub database ID with at most 20 digits."
  }
}

variable "github_environments" {
  description = "Protected GitHub environments allowed to request AWS credentials."
  type        = set(string)
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

  validation {
    condition = alltrue([
      for required in ["aws-baseline", "aws-data", "aws-images", "aws-infrastructure", "aws-training", "aws-trial-selection", "baseline-release", "heldout-release", "production", "production-benchmark"] :
      contains(var.github_environments, required)
    ]) && length(var.github_environments) == 10 && alltrue([for value in var.github_environments : can(regex("^[A-Za-z0-9_.-]+$", value))])
    error_message = "The exact ten workflow-specific protected environment names are required."
  }
}

variable "create_github_oidc_provider" {
  description = "Create GitHub's account-wide OIDC provider. Set false if the account already has it."
  type        = bool
  default     = false
}

variable "existing_github_oidc_provider_arn" {
  description = "Existing token.actions.githubusercontent.com provider ARN when create_github_oidc_provider is false."
  type        = string
  default     = ""

  validation {
    condition     = var.create_github_oidc_provider || can(regex("^arn:aws:iam::[0-9]{12}:oidc-provider/token\\.actions\\.githubusercontent\\.com$", var.existing_github_oidc_provider_arn))
    error_message = "Provide the exact existing GitHub OIDC provider ARN or set create_github_oidc_provider=true."
  }
}

variable "enable_budgets" {
  description = "Create the two AWS cost budgets only after the notification address and thresholds are approved."
  type        = bool
  default     = false
}

variable "budget_notification_email" {
  description = "Budget notification address. Keep blank until the owner approves it."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_budgets || can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.budget_notification_email))
    error_message = "A plausible notification email is required when budgets are enabled."
  }
}

variable "campaign_budget_usd" {
  description = "PRD maximum planned pre-credit campaign spend."
  type        = number
  default     = 40

  validation {
    condition     = var.campaign_budget_usd == 40
    error_message = "The approved campaign envelope is exactly USD 40; a change requires an ADR and owner approval."
  }
}

variable "maximum_out_of_pocket_usd" {
  description = "Owner-approved maximum payment-method exposure. Zero is deliberately stricter than the PRD ceiling."
  type        = number
  default     = 0

  validation {
    condition     = var.maximum_out_of_pocket_usd == 0
    error_message = "The owner declined out-of-pocket spend. This value must remain zero."
  }
}

variable "required_credit_reserve_usd" {
  description = "Applicable AWS credit that must remain after the planned campaign."
  type        = number
  default     = 40

  validation {
    condition     = var.required_credit_reserve_usd >= 40
    error_message = "At least USD 40 of applicable credit must be reserved."
  }
}

variable "enable_serving" {
  description = "Create the private Lambda candidate and IAM-authenticated candidate API after an immutable image digest exists."
  type        = bool
  default     = false
}

variable "enable_public_serving" {
  description = "Expose the production API and CloudFront site only after the private candidate gates pass. Production public serving is always protected by an independent 24-hour expiry; AWS Budgets are optional defense in depth."
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_public_serving || var.enable_serving
    error_message = "enable_public_serving requires enable_serving=true."
  }
}

variable "serving_image_uri" {
  description = "Immutable ECR image URI including @sha256 digest. Mutable tags are rejected."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_serving || can(regex("^[0-9]{12}\\.dkr\\.ecr\\.us-east-1\\.amazonaws\\.com/[a-z0-9/_-]+@sha256:[0-9a-f]{64}$", var.serving_image_uri))
    error_message = "enable_serving requires an immutable us-east-1 ECR URI with an @sha256 digest."
  }
}

variable "serving_git_sha" {
  description = "Exact lowercase 40-character Git commit served by the immutable Lambda image."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_serving || can(regex("^[0-9a-f]{40}$", var.serving_git_sha))
    error_message = "enable_serving requires the exact lowercase 40-character serving Git SHA."
  }
}

variable "serving_deployment_nonce" {
  description = "Unique GitHub workflow attempt and release identity used to publish a fresh immutable Lambda version."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_serving || can(regex("^[1-9][0-9]*-[1-9][0-9]*-[A-Za-z0-9][A-Za-z0-9._-]{2,62}$", var.serving_deployment_nonce))
    error_message = "enable_serving requires a deployment nonce formatted as <run-id>-<attempt>-<release-id>."
  }
}

variable "lambda_memory_mb" {
  description = "Memory assigned to the CPU inference function."
  type        = number
  default     = 4096

  validation {
    condition     = var.lambda_memory_mb >= 1024 && var.lambda_memory_mb <= 4096
    error_message = "lambda_memory_mb must remain between 1024 and the approved initial cap of 4096."
  }
}

variable "lambda_ephemeral_storage_mb" {
  description = "Ephemeral storage assigned to the inference function."
  type        = number
  default     = 2048

  validation {
    condition     = var.lambda_ephemeral_storage_mb >= 512 && var.lambda_ephemeral_storage_mb <= 2048
    error_message = "lambda_ephemeral_storage_mb must remain between 512 and 2048."
  }
}

variable "lambda_reserved_concurrency" {
  description = "Hard public-service scale bound."
  type        = number
  default     = 2

  validation {
    condition     = var.lambda_reserved_concurrency == 2
    error_message = "The PRD-approved reserved concurrency is exactly two."
  }
}

variable "lambda_timeout_seconds" {
  description = "Inference request timeout."
  type        = number
  default     = 30

  validation {
    condition     = var.lambda_timeout_seconds > 0 && var.lambda_timeout_seconds <= 30
    error_message = "The public function timeout may not exceed 30 seconds."
  }
}

variable "cloudwatch_log_retention_days" {
  description = "Short operational log retention; immutable evidence is exported separately."
  type        = number
  default     = 7

  validation {
    condition     = var.cloudwatch_log_retention_days == 7
    error_message = "Operational logs must use the approved seven-day retention."
  }
}

variable "alarm_notification_email" {
  description = "Optional address for actionable operational alarms. Requires email confirmation in AWS."
  type        = string
  default     = ""

  validation {
    condition     = var.alarm_notification_email == "" || can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.alarm_notification_email))
    error_message = "alarm_notification_email must be blank or a plausible address."
  }
}

variable "artifact_retention_days" {
  description = "Retention for final reports and promoted artifacts."
  type        = number
  default     = 365

  validation {
    condition     = var.artifact_retention_days >= 90
    error_message = "Final reports and promoted artifacts must be retained for at least 90 days."
  }
}
