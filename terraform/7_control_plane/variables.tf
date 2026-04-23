variable "aws_region" {
  type = string
}

variable "ecr_repository_uri" {
  description = "ECR URI for the control_plane container image"
  type        = string
}

variable "image_tag" {
  type    = string
  default = "day3"
}

variable "secret_read_policy_arn" {
  description = "ARN of devforge-secret-read from terraform/1_permissions"
  type        = string
}

variable "aurora_cluster_arn" {
  description = "Aurora cluster ARN from terraform/5_database"
  type        = string
}

variable "aurora_secret_arn" {
  description = "Aurora credentials secret ARN from terraform/5_database"
  type        = string
}

variable "github_app_id" {
  description = "GitHub App ID (created manually in Day 3)"
  type        = string
}
