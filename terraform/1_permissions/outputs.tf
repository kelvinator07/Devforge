output "openrouter_secret_arn" {
  description = "ARN of the OpenRouter API key secret"
  value       = aws_secretsmanager_secret.openrouter_api_key.arn
}

output "github_app_private_key_secret_arn" {
  description = "ARN of the GitHub App private key secret"
  value       = aws_secretsmanager_secret.github_app_private_key.arn
}

output "secret_read_policy_arn" {
  description = "Attach this to any role that needs to read DevForge secrets"
  value       = aws_iam_policy.devforge_secret_read.arn
}

output "setup_instructions" {
  value = <<-EOT

    DevForge permissions module deployed (v1 — using AWS-managed KMS key).

    Next steps:
      1. Put the OpenRouter API key:
         aws secretsmanager put-secret-value \
           --secret-id devforge/openrouter-api-key \
           --secret-string 'sk-or-v1-...'

      2. After creating the GitHub App (Day 3), upload its private key:
         aws secretsmanager put-secret-value \
           --secret-id devforge/github-app-private-key \
           --secret-string "$(cat path/to/app.private-key.pem)"

      3. Attach the secret-read policy to Fargate task role (6_worker) + Lambda role (7_control_plane).

    v2 upgrade: grant kms:* to aiengineer group, then re-introduce customer-managed CMK.
  EOT
}
