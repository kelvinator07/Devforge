variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "kms_cmk_arn" {
  description = "ARN of an externally-managed KMS CMK to encrypt secrets with. Leave empty to provision one in this module (requires kms:CreateKey on the caller)."
  type        = string
  default     = ""
}
