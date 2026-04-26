#!/usr/bin/env bash
# Emit `export` lines for the env vars that DevForge CLI scripts need
# when running with DEVFORGE_BACKEND=aws. Pulls live values from the
# deployed Terraform state — no .env file maintenance, no drift after
# `terraform apply` rotates a secret suffix.
#
# Usage:
#     eval "$(./scripts/aws_env.sh)"
#     uv run python -m scripts.index_repo 1
#
# Idempotent; safe to re-source after any TF apply.
#
# Reads:
#   terraform/5_database/terraform.tfstate
#   terraform/7_control_plane/terraform.tfstate
#   aws sts get-caller-identity
#
# Doesn't touch DEVFORGE_ADMIN_TOKEN, OPENROUTER_API_KEY, LANGFUSE_*,
# CLERK_JWKS_URL, or GitHub App keys — those already live in .env.local
# and every script auto-loads them via load_dotenv.

set -euo pipefail
cd "$(dirname "$0")/.."

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
CLUSTER_ARN=$(cd terraform/5_database && terraform output -raw aurora_cluster_arn)
SECRET_ARN=$(cd terraform/5_database && terraform output -raw aurora_secret_arn)
API_URL=$(cd terraform/7_control_plane && terraform output -raw api_endpoint)

cat <<EOF
export DEVFORGE_BACKEND=aws
export CONTROL_PLANE_API="$API_URL"
export AURORA_CLUSTER_ARN="$CLUSTER_ARN"
export AURORA_SECRET_ARN="$SECRET_ARN"
export AURORA_DATABASE=devforge
export VECTOR_BUCKET="devforge-vectors-$ACCOUNT"
EOF
