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

# AWSBackend dependencies — required for the orchestrator running in the
# Fargate container. RAG store + Aurora job-event writes.
variable "vector_bucket_name" {
  description = "S3 Vector bucket name (devforge-vectors-<account>) for the orchestrator's RAG store."
  type        = string
}

variable "aurora_cluster_arn" {
  description = "Aurora cluster ARN (output of 5_database). Worker writes job events here."
  type        = string
}

variable "aurora_secret_arn" {
  description = "Aurora credentials secret ARN (output of 5_database)."
  type        = string
}

variable "devforge_admin_token" {
  description = "Admin token. The worker's orchestrator uses admin_headers() to call back into the control plane (tenant lookup, install token, approval consume); without this token those callbacks 401."
  type        = string
  sensitive   = true
}
