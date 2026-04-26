variable "aws_region" {
  description = "AWS region for the S3 bucket. CloudFront is global; ACM for the distribution must live in us-east-1."
  type        = string
}

variable "bucket_name" {
  description = "S3 bucket name for the static frontend build (must be globally unique)."
  type        = string
  default     = "devforge-frontend"
}

variable "domain" {
  description = "Optional custom domain (e.g. devforge.example.com). Empty string = use default CloudFront domain only."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN in us-east-1 for the custom domain. Required only when domain is set."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route53 hosted zone id for the apex domain. Required only when domain is set."
  type        = string
  default     = ""
}
