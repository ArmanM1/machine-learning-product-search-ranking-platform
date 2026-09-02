variable "aws_region" {
  type    = string
  default = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "Bootstrap is constrained to us-east-1."
  }
}

variable "project_name" {
  type    = string
  default = "product-search-ranking"
}

variable "owner_alias" {
  type = string
}
