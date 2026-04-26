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

# ============================================================================
# Worker / ECS RunTask wiring (#7 — POST /jobs dispatches via ecs.run_task in
# AWS mode). Pulled from terraform/6_worker outputs by scripts/deploy_aws.sh.
# ============================================================================
variable "ecs_cluster_name" {
  description = "Worker ECS cluster name (output from 6_worker)"
  type        = string
}

variable "ecs_task_definition_arn" {
  description = "Worker task definition ARN (output from 6_worker)"
  type        = string
}

variable "ecs_subnet_ids" {
  description = "Subnet IDs to launch worker tasks in (output from 6_worker)"
  type        = list(string)
}

variable "ecs_security_group_id" {
  description = "Security group for worker tasks (output from 6_worker)"
  type        = string
}

variable "task_execution_role_arn" {
  description = "Worker task EXECUTION role ARN — needed for iam:PassRole (output from 6_worker)"
  type        = string
}

variable "task_role_arn" {
  description = "Worker TASK role ARN — needed for iam:PassRole (output from 6_worker)"
  type        = string
}
