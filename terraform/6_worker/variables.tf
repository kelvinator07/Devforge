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

# Runtime env for the worker container. CONTROL_PLANE_API is required so the
# orchestrator's httpx callbacks (tenant lookup, install token, status updates)
# reach the API Gateway. LangFuse keys are optional — empty strings disable
# tracing without breaking the worker.

variable "control_plane_api" {
  description = "Public URL of the control plane API Gateway. Pass via TF_VAR from 7_control_plane outputs after that module is applied."
  type        = string
  default     = ""
}

variable "langfuse_public_key" {
  description = "LangFuse public key. Empty disables observability."
  type        = string
  default     = ""
  sensitive   = true
}

variable "langfuse_secret_key" {
  description = "LangFuse secret key. Empty disables observability."
  type        = string
  default     = ""
  sensitive   = true
}

variable "langfuse_host" {
  description = "LangFuse host URL."
  type        = string
  default     = "https://cloud.langfuse.com"
}
