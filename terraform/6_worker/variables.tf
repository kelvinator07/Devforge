variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "ecr_repository_uri" {
  description = "ECR repo URI for the worker image (e.g. 808379775689.dkr.ecr.us-east-1.amazonaws.com/devforge-worker)"
  type        = string
}

variable "image_tag" {
  description = "Docker image tag to deploy (e.g. day2)"
  type        = string
  default     = "day2"
}

variable "secret_read_policy_arn" {
  description = "ARN of devforge-secret-read from terraform/1_permissions"
  type        = string
}
