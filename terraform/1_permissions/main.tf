terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# ========================================
# Secrets Manager — encrypted with AWS-managed `aws/secretsmanager` key.
# NOTE: v1 trade-off. The aiengineer IAM user lacks `kms:CreateKey`, so we skip the
# customer-managed CMK. Upgrade path (v2): grant `kms:*` to the user/group, then
# add aws_kms_key + `kms_key_id = aws_kms_key.devforge_secrets.id` on both secrets.
# ========================================
resource "aws_secretsmanager_secret" "openrouter_api_key" {
  name                    = "devforge/openrouter-api-key"
  description             = "OpenRouter API key used by DevForge worker agents"
  recovery_window_in_days = 0  # immediate delete on destroy (demo-grade)
}

resource "aws_secretsmanager_secret_version" "openrouter_placeholder" {
  secret_id     = aws_secretsmanager_secret.openrouter_api_key.id
  secret_string = "PLACEHOLDER_REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_string]  # don't overwrite user-set value on re-apply
  }
}

resource "aws_secretsmanager_secret" "github_app_private_key" {
  name                    = "devforge/github-app-private-key"
  description             = "GitHub App private key (PEM) used by DevForge control plane"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "github_app_private_key_placeholder" {
  secret_id     = aws_secretsmanager_secret.github_app_private_key.id
  secret_string = "PLACEHOLDER_REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ========================================
# IAM policy document: lets a principal read the two secrets.
# (Attached to Fargate task role in 6_worker and Lambda role in 7_control_plane)
# ========================================
data "aws_iam_policy_document" "secret_read" {
  statement {
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      aws_secretsmanager_secret.openrouter_api_key.arn,
      aws_secretsmanager_secret.github_app_private_key.arn,
    ]
  }
}

resource "aws_iam_policy" "devforge_secret_read" {
  name        = "devforge-secret-read"
  description = "Read DevForge secrets"
  policy      = data.aws_iam_policy_document.secret_read.json
}
