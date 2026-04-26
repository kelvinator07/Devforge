#!/usr/bin/env bash
# DevForge AWS deployment — codifies the Day 1-3 push sequence so it's re-runnable.
#
# Usage:
#   ./scripts/deploy_aws.sh all           # full deploy in dependency order
#   ./scripts/deploy_aws.sh permissions   # just 1_permissions (Secrets Manager + CMK + IAM policy)
#   ./scripts/deploy_aws.sh sagemaker     # just 2_sagemaker (embedding endpoint)
#   ./scripts/deploy_aws.sh vectors       # creates the S3 Vector bucket worker uses for RAG
#   ./scripts/deploy_aws.sh database      # just 5_database + run migrations
#   ./scripts/deploy_aws.sh worker        # build + push worker image + apply 6_worker
#   ./scripts/deploy_aws.sh control-plane # build + push cp image + apply 7_control_plane
#   ./scripts/deploy_aws.sh frontend      # build static export + sync to S3 + invalidate CloudFront
#   ./scripts/deploy_aws.sh destroy       # tear everything down (reverse order)
#
# Prereqs: aws cli signed in, docker running, uv installed.
# Reads terraform/*/terraform.tfvars.

set -euo pipefail

cd "$(dirname "$0")/.."
export DEVFORGE_BACKEND=aws
export AWS_REGION="${AWS_REGION:-us-east-1}"
# Every TF module declares `var.aws_region`; export it once here so individual
# modules don't need their own tfvars line for it.
export TF_VAR_aws_region="$AWS_REGION"
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

create_s3vectors_bucket() {
  local bucket="devforge-vectors-${ACCOUNT}"
  aws s3vectors create-vector-bucket \
    --vector-bucket-name "$bucket" --region "$AWS_REGION" 2>/dev/null \
    && echo "created vector bucket: $bucket" \
    || echo "vector bucket exists: $bucket"
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

  vectors)
    # Create the S3 Vector bucket the worker uses for RAG. Per-tenant
    # indexes (tenant_<id>_codebase) are created on demand by
    # `scripts.index_repo` the first time a tenant is indexed.
    create_s3vectors_bucket
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
    # OpenAI key for Agents-SDK default trace processor. Optional — empty
    # string leaves OpenAI traces disabled, LangFuse unaffected.
    export TF_VAR_openai_api_key="${OPENAI_API_KEY:-}"
    # AWSBackend deps — orchestrator writes events to Aurora + reads RAG
    # from S3 Vectors. Pulled from the existing 5_database state and
    # derived from the AWS account id.
    export TF_VAR_vector_bucket_name="devforge-vectors-${ACCOUNT}"
    export TF_VAR_aurora_cluster_arn=$(cd terraform/5_database && terraform output -raw aurora_cluster_arn)
    export TF_VAR_aurora_secret_arn=$(cd terraform/5_database && terraform output -raw aurora_secret_arn)
    export TF_VAR_devforge_admin_token="${DEVFORGE_ADMIN_TOKEN:?DEVFORGE_ADMIN_TOKEN must be set in the host env (source .env.local)}"
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
    # Use the family name (not the revisioned ARN) so ecs.run_task() always
    # resolves to the latest ACTIVE revision. Pinning to a specific revision
    # breaks the moment a worker re-apply auto-deregisters the old one.
    export TF_VAR_ecs_task_definition_arn=$(cd "$WORKER_DIR" && terraform output -raw task_definition_family)
    export TF_VAR_ecs_security_group_id=$(cd "$WORKER_DIR" && terraform output -raw security_group_id)
    export TF_VAR_ecs_subnet_ids=$(cd "$WORKER_DIR" && terraform output -json subnet_ids)
    export TF_VAR_task_execution_role_arn=$(cd "$WORKER_DIR" && terraform output -raw task_execution_role_arn)
    export TF_VAR_task_role_arn=$(cd "$WORKER_DIR" && terraform output -raw task_role_arn)
    # Aurora secret has a random suffix that changes on re-deploy; pull
    # current values from 5_database state to keep tfvars from going stale.
    export TF_VAR_aurora_cluster_arn=$(cd terraform/5_database && terraform output -raw aurora_cluster_arn)
    export TF_VAR_aurora_secret_arn=$(cd terraform/5_database && terraform output -raw aurora_secret_arn)
    # Clerk JWKS URL for browser-side JWT validation (optional — empty
    # disables Clerk auth path; admin token still works).
    export TF_VAR_clerk_jwks_url="${CLERK_JWKS_URL:-}"
    # AWSBackend's eager init reads VECTOR_BUCKET; control plane doesn't
    # query vectors directly but the env var must be present.
    export TF_VAR_vector_bucket_name="devforge-vectors-${ACCOUNT}"
    # Admin token used by /tenants/onboard, /approvals POST, and CLI tooling.
    export TF_VAR_devforge_admin_token="${DEVFORGE_ADMIN_TOKEN:?DEVFORGE_ADMIN_TOKEN must be set in the host env (source .env.local)}"
    # CORS: start from the user's DEVFORGE_CORS_ORIGINS (or the localhost
    # default), then auto-append the CloudFront site URL when 8_frontend
    # has been deployed. The append always runs so a sourced .env.local
    # with a localhost-only value can't accidentally suppress the prod origin.
    CORS_BASE="${DEVFORGE_CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"
    if [ -f terraform/8_frontend/terraform.tfstate ]; then
      FRONTEND_URL=$(cd terraform/8_frontend && terraform output -raw site_url 2>/dev/null || echo "")
      if [ -n "$FRONTEND_URL" ] && [[ "$CORS_BASE" != *"$FRONTEND_URL"* ]]; then
        CORS_BASE="$CORS_BASE,$FRONTEND_URL"
      fi
    fi
    export TF_VAR_cors_origins="$CORS_BASE"
    tf_apply terraform/7_control_plane
    # Force the Lambda to re-pull the just-pushed image. TF only sees
    # `image_uri = ${repo}:${tag}` as a string, so when we push a new digest
    # under the SAME tag it considers the function unchanged. update-function-code
    # against the same uri picks up whatever digest the tag currently resolves to.
    echo "== forcing Lambda image refresh =="
    aws lambda update-function-code \
      --function-name devforge-control-plane \
      --image-uri "${ECR_BASE}/devforge-control-plane:${CP_TAG:-day7}" \
      --query 'CodeSha256' --output text
    aws lambda wait function-updated --function-name devforge-control-plane
    ;;

  frontend)
    # Static-export → S3 → CloudFront. Requires next.config.ts with output:"export".
    # Bucket names are globally unique — suffix with account id to avoid
    # collisions on first deploy. Honors a user-provided override via tfvars.
    export TF_VAR_bucket_name="${TF_VAR_bucket_name:-devforge-frontend-$ACCOUNT}"
    tf_apply terraform/8_frontend
    BUCKET=$(cd terraform/8_frontend && terraform output -raw bucket_name)
    DIST=$(cd terraform/8_frontend && terraform output -raw cloudfront_distribution_id)
    SITE=$(cd terraform/8_frontend && terraform output -raw site_url)
    echo "== building static frontend (uses frontend/.env.production for NEXT_PUBLIC_*) =="
    # Next.js loads .env.local for *all* environments and it overrides
    # .env.production — disastrous for static builds because the local
    # `localhost:8001` API URL gets baked into the production bundle. Move
    # it aside for the build, restore on EXIT (even on failure).
    if [ -f frontend/.env.local ]; then
      mv frontend/.env.local frontend/.env.local.deploy-bak
      trap 'mv frontend/.env.local.deploy-bak frontend/.env.local 2>/dev/null || true' EXIT
    fi
    (cd frontend && npm install && npm run build)
    if [ -f frontend/.env.local.deploy-bak ]; then
      mv frontend/.env.local.deploy-bak frontend/.env.local
      trap - EXIT
    fi
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
    bash "$0" vectors
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
    tf_destroy terraform/2_sagemaker || true
    tf_destroy terraform/1_permissions || true
    aws ecr delete-repository --repository-name devforge-worker --region "$AWS_REGION" --force 2>/dev/null || true
    aws ecr delete-repository --repository-name devforge-control-plane --region "$AWS_REGION" --force 2>/dev/null || true
    # Per-tenant indexes (tenant_<id>_codebase) are deleted along with the
    # bucket; no need to enumerate them here.
    aws s3vectors delete-vector-bucket --vector-bucket-name "devforge-vectors-${ACCOUNT}" --region "$AWS_REGION" 2>/dev/null || true
    echo "DevForge AWS resources destroyed."
    ;;

  *)
    echo "usage: $0 {all|permissions|sagemaker|vectors|database|worker|control-plane|frontend|destroy}"
    exit 1
    ;;
esac
