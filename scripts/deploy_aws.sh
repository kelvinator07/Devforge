#!/usr/bin/env bash
# DevForge AWS deployment — codifies the Day 1-3 push sequence so it's re-runnable.
#
# Usage:
#   ./scripts/deploy_aws.sh all           # apply 1,2,3,5,6,7 in order + build + push + migrate
#   ./scripts/deploy_aws.sh permissions   # just 1_permissions
#   ./scripts/deploy_aws.sh sagemaker     # just 2_sagemaker
#   ./scripts/deploy_aws.sh ingestion     # build ingest lambda zip + apply 3_ingestion
#   ./scripts/deploy_aws.sh database      # just 5_database + run migrations
#   ./scripts/deploy_aws.sh worker        # build + push worker image + apply 6_worker
#   ./scripts/deploy_aws.sh control-plane # build + push cp image + apply 7_control_plane
#   ./scripts/deploy_aws.sh destroy       # tear everything down (reverse order)
#
# Prereqs: aws cli signed in, docker running, uv installed.
# Reads terraform/*/terraform.tfvars.

set -euo pipefail

cd "$(dirname "$0")/.."
export DEVFORGE_BACKEND=aws
export AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_BASE="${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

tf_apply() {
  local dir="$1"
  echo "== terraform apply :: $dir =="
  ( cd "$dir" && terraform init -input=false -upgrade=false >/dev/null && terraform apply -auto-approve -input=false )
}

tf_destroy() {
  local dir="$1"
  echo "== terraform destroy :: $dir =="
  ( cd "$dir" && terraform destroy -auto-approve -input=false )
}

ecr_login() {
  aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_BASE" >/dev/null
}

ensure_ecr_repo() {
  local repo="$1"
  aws ecr describe-repositories --repository-names "$repo" --region "$AWS_REGION" >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$repo" --region "$AWS_REGION" --image-scanning-configuration scanOnPush=true >/dev/null
}

build_push() {
  # Always builds from the devforge/ repo root so the image can pull in the
  # full backend/ tree (common + ingest + mcp + worker or control_plane).
  local dockerfile="$1" repo="$2" tag="${3:-latest}"
  ensure_ecr_repo "$repo"
  ecr_login
  docker build --platform linux/amd64 -f "$dockerfile" -t "${ECR_BASE}/${repo}:${tag}" .
  docker push "${ECR_BASE}/${repo}:${tag}"
}

build_ingest_zip() {
  echo "== building ingest lambda_function.zip =="
  ( cd backend/ingest && uv sync && uv run python package.py )
}

create_s3vectors_bucket_and_index() {
  local bucket="devforge-vectors-${ACCOUNT}"
  aws s3vectors create-vector-bucket --vector-bucket-name "$bucket" --region "$AWS_REGION" 2>/dev/null || true
  aws s3vectors create-index \
    --vector-bucket-name "$bucket" \
    --index-name "${VECTOR_INDEX:-financial-research}" \
    --dimension 384 --distance-metric cosine --data-type float32 \
    --region "$AWS_REGION" 2>/dev/null || true
}

cmd="${1:-}"

case "$cmd" in
  permissions)
    tf_apply terraform/1_permissions
    echo "NOTE: populate the two secrets before deploying worker / control plane:"
    echo "  aws secretsmanager put-secret-value --secret-id devforge/openrouter-api-key --secret-string 'sk-or-v1-...'"
    echo "  aws secretsmanager put-secret-value --secret-id devforge/github-app-private-key --secret-string \"\$(cat path/to/app.pem)\""
    ;;

  sagemaker)
    tf_apply terraform/2_sagemaker
    ;;

  ingestion)
    build_ingest_zip
    tf_apply terraform/3_ingestion
    create_s3vectors_bucket_and_index
    ;;

  database)
    tf_apply terraform/5_database
    CLUSTER_ARN=$(cd terraform/5_database && terraform output -raw aurora_cluster_arn)
    SECRET_ARN=$(cd terraform/5_database && terraform output -raw aurora_secret_arn)
    AURORA_CLUSTER_ARN="$CLUSTER_ARN" AURORA_SECRET_ARN="$SECRET_ARN" \
      uv run python -m backend.database.run_migrations
    ;;

  worker)
    # Dockerfile lives under backend/worker/ but build context is the repo root.
    build_push backend/worker/Dockerfile devforge-worker "${WORKER_TAG:-day7}"
    # Forward observability + control-plane URL from the host env. Empty
    # values cleanly disable LangFuse / leave CONTROL_PLANE_API blank (the
    # control plane overrides it via containerOverrides at run-task time).
    export TF_VAR_langfuse_public_key="${LANGFUSE_PUBLIC_KEY:-}"
    export TF_VAR_langfuse_secret_key="${LANGFUSE_SECRET_KEY:-}"
    export TF_VAR_langfuse_host="${LANGFUSE_HOST:-https://cloud.langfuse.com}"
    # If 7_control_plane has been deployed, pre-populate the worker task def
    # with its URL too (helps standalone `aws ecs run-task` smoke tests).
    if [ -f terraform/7_control_plane/terraform.tfstate ]; then
      export TF_VAR_control_plane_api=$(cd terraform/7_control_plane && terraform output -raw api_endpoint 2>/dev/null || echo "")
    fi
    tf_apply terraform/6_worker
    ;;

  control-plane)
    build_push backend/control_plane/Dockerfile devforge-control-plane "${CP_TAG:-day7}"
    # #7: pull worker outputs and pass them as TF_VAR_* env vars so the
    # control plane Lambda can ecs.run_task() against the worker cluster.
    WORKER_DIR=terraform/6_worker
    export TF_VAR_ecs_cluster_name=$(cd "$WORKER_DIR" && terraform output -raw cluster_name)
    export TF_VAR_ecs_task_definition_arn=$(cd "$WORKER_DIR" && terraform output -raw task_definition_arn)
    export TF_VAR_ecs_security_group_id=$(cd "$WORKER_DIR" && terraform output -raw security_group_id)
    export TF_VAR_ecs_subnet_ids=$(cd "$WORKER_DIR" && terraform output -json subnet_ids)
    export TF_VAR_task_execution_role_arn=$(cd "$WORKER_DIR" && terraform output -raw task_execution_role_arn)
    export TF_VAR_task_role_arn=$(cd "$WORKER_DIR" && terraform output -raw task_role_arn)
    # Clerk JWKS URL for browser-side JWT validation (optional — empty
    # disables Clerk auth path; admin token still works).
    export TF_VAR_clerk_jwks_url="${CLERK_JWKS_URL:-}"
    tf_apply terraform/7_control_plane
    ;;

  frontend)
    # Static-export → S3 → CloudFront. Requires next.config.ts with output:"export".
    tf_apply terraform/8_frontend
    BUCKET=$(cd terraform/8_frontend && terraform output -raw bucket_name)
    DIST=$(cd terraform/8_frontend && terraform output -raw cloudfront_distribution_id)
    SITE=$(cd terraform/8_frontend && terraform output -raw site_url)
    echo "== building static frontend (uses frontend/.env.production for NEXT_PUBLIC_*) =="
    (cd frontend && npm install && npm run build)
    echo "== syncing out/ to s3://${BUCKET}/ =="
    aws s3 sync frontend/out/ "s3://${BUCKET}/" --delete --region "$AWS_REGION"
    echo "== invalidating CloudFront cache =="
    aws cloudfront create-invalidation \
      --distribution-id "$DIST" --paths "/*" \
      --query "Invalidation.Id" --output text
    echo "deployed -> $SITE"
    ;;

  all)
    bash "$0" permissions
    bash "$0" sagemaker
    bash "$0" ingestion
    bash "$0" database
    bash "$0" worker
    bash "$0" control-plane
    bash "$0" frontend
    ;;

  destroy)
    tf_destroy terraform/8_frontend || true
    tf_destroy terraform/7_control_plane || true
    tf_destroy terraform/5_database || true
    tf_destroy terraform/6_worker || true
    tf_destroy terraform/3_ingestion || true
    tf_destroy terraform/2_sagemaker || true
    tf_destroy terraform/1_permissions || true
    aws ecr delete-repository --repository-name devforge-worker --region "$AWS_REGION" --force 2>/dev/null || true
    aws ecr delete-repository --repository-name devforge-control-plane --region "$AWS_REGION" --force 2>/dev/null || true
    aws s3vectors delete-index --vector-bucket-name "devforge-vectors-${ACCOUNT}" --index-name "${VECTOR_INDEX:-financial-research}" --region "$AWS_REGION" 2>/dev/null || true
    aws s3vectors delete-vector-bucket --vector-bucket-name "devforge-vectors-${ACCOUNT}" --region "$AWS_REGION" 2>/dev/null || true
    echo "DevForge AWS resources destroyed."
    ;;

  *)
    echo "usage: $0 {all|permissions|sagemaker|ingestion|database|worker|control-plane|frontend|destroy}"
    exit 1
    ;;
esac
