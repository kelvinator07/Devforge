output "bucket_name" {
  description = "Static frontend bucket — `aws s3 sync ./out/ s3://<this>/` to deploy."
  value       = aws_s3_bucket.frontend.id
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution id — needed for `aws cloudfront create-invalidation`."
  value       = aws_cloudfront_distribution.frontend.id
}

output "cloudfront_domain_name" {
  description = "CloudFront default domain (e.g. d1234.cloudfront.net). Use this when no custom domain is configured."
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "site_url" {
  description = "Resolved public URL — custom domain when set, otherwise the CloudFront default."
  value       = local.use_custom_domain ? "https://${var.domain}" : "https://${aws_cloudfront_distribution.frontend.domain_name}"
}
