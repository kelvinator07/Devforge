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
# Customer-managed KMS key (CMK) for Secrets Manager.
#
# Path A: TF provisions the key here (default, when var.kms_cmk_arn is empty).
# Path B: an admin pre-creates the key out-of-band and passes its ARN via
#         var.kms_cmk_arn — useful when the deploying user lacks kms:CreateKey.
# ========================================
locals {
  cmk_provisioned = var.kms_cmk_arn == ""
  cmk_arn         = local.cmk_provisioned ? aws_kms_key.devforge[0].arn : var.kms_cmk_arn
}

resource "aws_kms_key" "devforge" {
  count                   = local.cmk_provisioned ? 1 : 0
  description             = "DevForge — encrypts Secrets Manager entries"
  enable_key_rotation     = true
  deletion_window_in_days = 7 # min 7, max 30. AWS hard-floors at 7.
  tags                    = { Project = "DevForge" }
}

resource "aws_kms_alias" "devforge" {
  count         = local.cmk_provisioned ? 1 : 0
  name          = "alias/devforge-secrets"
  target_key_id = aws_kms_key.devforge[0].key_id
}

# Key policy: grant root + Secrets Manager service the ability to use the
# key. The consumer IAM roles get kms:Decrypt via aws_iam_policy.devforge_secret_read
# below — that's enough since AWS evaluates BOTH the key policy and the IAM
# policy and a Service principal here lets Secrets Manager forward decrypt
# requests on behalf of any caller that has the IAM perm.
resource "aws_kms_key_policy" "devforge" {
  count  = local.cmk_provisioned ? 1 : 0
  key_id = aws_kms_key.devforge[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "RootAccountFullAccess"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      # The deploying caller (whatever IAM user/role TF runs as) needs
      # operational KMS perms so Secrets Manager can encrypt new secret
      # values on its behalf. Without this, CreateSecret hits
      # AccessDeniedException: Access to KMS is not allowed.
      {
        Sid       = "AllowDeployingCaller"
        Effect    = "Allow"
        Principal = { AWS = data.aws_caller_identity.current.arn }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:GenerateDataKeyWithoutPlaintext",
          "kms:ReEncrypt*",
          "kms:DescribeKey",
          # Secrets Manager creates a KMS grant per-secret when associating
          # a CMK; without CreateGrant the CreateSecret call fails with
          # "AccessDeniedException: Access to KMS is not allowed".
          "kms:CreateGrant",
        ]
        Resource = "*"
      },
      {
        Sid       = "AllowSecretsManagerService"
        Effect    = "Allow"
        Principal = { Service = "secretsmanager.amazonaws.com" }
        Action    = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource  = "*"
      },
    ]
  })
}

# ========================================
# Secrets Manager — encrypted with the CMK above.
# ========================================
resource "aws_secretsmanager_secret" "openrouter_api_key" {
  name                    = "devforge/openrouter-api-key"
  description             = "OpenRouter API key used by DevForge worker agents"
  recovery_window_in_days = 0 # immediate delete on destroy (demo-grade)
  kms_key_id              = local.cmk_arn
}

resource "aws_secretsmanager_secret_version" "openrouter_placeholder" {
  secret_id     = aws_secretsmanager_secret.openrouter_api_key.id
  secret_string = "PLACEHOLDER_REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_string] # don't overwrite user-set value on re-apply
  }
}

resource "aws_secretsmanager_secret" "github_app_private_key" {
  name                    = "devforge/github-app-private-key"
  description             = "GitHub App private key (PEM) used by DevForge control plane"
  recovery_window_in_days = 0
  kms_key_id              = local.cmk_arn
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
# (Attached to Fargate task role in 4_worker and Lambda role in 5_control_plane)
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

  # Consumer roles need kms:Decrypt to fetch the underlying secret value.
  # Scoped to the Secrets Manager service via kms:ViaService so direct
  # kms:Decrypt API calls (outside SM) are still denied.
  statement {
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [local.cmk_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "devforge_secret_read" {
  name        = "devforge-secret-read"
  description = "Read DevForge secrets"
  policy      = data.aws_iam_policy_document.secret_read.json
}
