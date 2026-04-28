# DevForge — AWS deploy + threat model

The operational companion to the project [README](README.md). The README covers the project pitch, architecture, and local quickstart; this file covers everything you need when shipping to AWS — the end-to-end runbook, the threat model the deploy enforces, and the v1 trade-offs you should know about before you bet on it.

## Push to AWS

`DEVFORGE_BACKEND=local|aws` is the only switch; the same code runs both ways. Below is the end-to-end runbook for a fresh AWS account. All the heavy lifting goes through `scripts/deploy_aws.sh` — each subcommand is idempotent and mirrors a single Terraform module.

### Prerequisites

| Requirement | Why |
|---|---|
| AWS CLI configured (`aws sts get-caller-identity` resolves) | Terraform + boto3 use these creds |
| IAM perms on the deploying user: VPC, ECS, Lambda, IAM, Secrets Manager, KMS (incl. `kms:CreateKey`), RDS, S3, CloudFront, SageMaker, API Gateway, Route 53 (if using a custom domain) | One-shot grant to the user; see `terraform/1_permissions/main.tf` for the full surface |
| Docker Desktop (or daemon) running | Builds the worker + control plane container images for ECR |
| `uv` 0.11+ installed | Python package and project manager |
| Node 20+ + `npm` | Builds the static frontend export |
| OpenRouter API key | LLM inference for all agents |
| GitHub App created (one per AWS environment) — note the App ID + download the PEM | Per-tenant install tokens; see `scripts/install_github_app.py` for the onboarding helper |
| Clerk **production** application (`pk_live_…`, `sk_live_…`, JWKS URL) | Browser-side JWT auth on the deployed control plane |
| LangFuse cloud project (optional) — public + secret keys + project id | One-trace-per-job observability + the `view trace ↗` deep-link |

### Step 0 — Populate `.env.local` and the per-module `terraform.tfvars`

Local `.env.local` (used by the deploy script + migrations):
```
OPENROUTER_API_KEY=sk-or-v1-…
DEVFORGE_ADMIN_TOKEN=…long-random…
GITHUB_APP_ID=…
GITHUB_APP_PRIVATE_KEY_PATH=secrets/github-app.pem
CLERK_JWKS_URL=https://<your-app>.clerk.accounts.dev/.well-known/jwks.json
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-…
LANGFUSE_SECRET_KEY=sk-lf-…
AWS_REGION=us-east-1
```

For each module, copy `terraform.tfvars.example` → `terraform.tfvars` and fill in the placeholders. Cross-module ARNs (Aurora, secrets, worker outputs) get filled in as you progress through the steps.

### Step 1 — Permissions + Secrets Manager + CMK

```bash
./scripts/deploy_aws.sh permissions
```

Then seed the two secret values the script prints (one-time per deploy):
```bash
aws secretsmanager put-secret-value \
  --secret-id devforge/openrouter-api-key \
  --secret-string "$OPENROUTER_API_KEY"
aws secretsmanager put-secret-value \
  --secret-id devforge/github-app-private-key \
  --secret-string "$(cat secrets/github-app.pem)"
```

Verify the CMK is wired:
```bash
aws secretsmanager describe-secret --secret-id devforge/openrouter-api-key \
  --query KmsKeyId --output text
# Expect: arn:aws:kms:…:key/…   (NOT alias/aws/secretsmanager)
```

### Step 2 — SageMaker embedding endpoint + S3 Vector bucket

```bash
./scripts/deploy_aws.sh sagemaker     # ~5 min — endpoint cold-start
./scripts/deploy_aws.sh vectors       # creates the S3 Vector bucket DevForge's RAG uses
```

Per-tenant vector indexes (`tenant_<id>_codebase`) are created on demand the first time `scripts.index_repo` runs against that tenant — no upfront global index needed.

### Step 3 — Aurora Serverless v2 + migrations

```bash
./scripts/deploy_aws.sh database      # ~3 min — cluster boot
```

The subcommand applies the four schema migrations against Aurora automatically once the cluster is `available`. The runner is idempotent: re-runs after a manual schema tweak skip already-applied columns instead of crashing.

### Step 4 — Worker Fargate cluster

```bash
./scripts/deploy_aws.sh worker        # builds + pushes worker image, applies 4_worker
```

This step propagates `LANGFUSE_*` from your shell env into the task definition. If you skipped Step 0's LangFuse setup, the values stay empty and tracing silently no-ops.

### Step 5 — Control plane Lambda + API Gateway

```bash
./scripts/deploy_aws.sh control-plane # ~2 min — Lambda + HTTP API
```

This step automatically wires:
- 6 outputs from `4_worker` (cluster name, task def, subnets, sg, role ARNs) → `5_control_plane` via `TF_VAR_*` so the Lambda can `ecs.run_task()` against the worker cluster.
- `CLERK_JWKS_URL` from your shell env → Lambda environment.

After it completes, capture the API endpoint:
```bash
API_URL=$(cd terraform/5_control_plane && terraform output -raw api_endpoint)
echo "$API_URL"  # https://abc123.execute-api.us-east-1.amazonaws.com
```

### Step 6 — Onboard your tenant + index the demo repo

The control plane is up but has no tenants yet. Load the deployed state into your shell once, then run the onboarding scripts:

```bash
eval "$(./scripts/aws_env.sh)"

# Now `DEVFORGE_BACKEND=aws`, `CONTROL_PLANE_API`, `AURORA_*`, and `VECTOR_BUCKET` are all exported. Combined with `.env.local` for keys and tokens, every script "just works" against the deployed stack.

uv run python -m scripts.install_github_app

# Link your tenant to your Clerk identity so /tenants/me resolves:
uv run python -m scripts.link_tenant_clerk_identity 1 --user user_<your-id>

# Seed the demo repo + RAG index against AWS:
uv run python -m scripts.populate_demo_repo 1
uv run python -m scripts.index_repo 1
```

`scripts/aws_env.sh` reads the live Terraform state every call, so any re-apply that rotates a secret suffix is auto-picked-up — re-source the helper, no other changes needed.

### Step 7 — Frontend

Create `frontend/.env.production` (gitignored) with prod values:
```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_…
CLERK_SECRET_KEY=sk_live_…
NEXT_PUBLIC_DEVFORGE_API=<API_URL from step 5>
NEXT_PUBLIC_LANGFUSE_PROJECT_ID=…
NEXT_PUBLIC_LANGFUSE_HOST=https://cloud.langfuse.com
```

Then:
```bash
./scripts/deploy_aws.sh frontend      # TF apply, npm build, S3 sync, CloudFront invalidation
```

The script prints the live URL (e.g. `https://d1234.cloudfront.net`). Sign in via Clerk, click **+ New ticket**, watch a Fargate task spin up.

### Step 8 — Verify end-to-end

```bash
# 1. Worker can reach the control plane:
aws logs tail /aws/ecs/devforge-worker --follow --since 10m

# 2. Control plane is dispatching tasks:
aws logs tail /aws/lambda/devforge-control-plane --follow --since 10m

# 3. CloudFront 404→/index.html SPA fallback:
curl -I https://<cloudfront-domain>/jobs/123
# Expect: HTTP/2 200 (not 404 — CloudFront's custom_error_response rewrites)

# 4. LangFuse trace deep-link:
# Click "view trace ↗" on any /jobs/[id] page. Should land on a populated trace tree (Lead → Backend → QA spans).
```

### One-shot variants

```bash
./scripts/deploy_aws.sh all         # all 7 modules in dependency order
./scripts/deploy_aws.sh worker      # iterate on the worker image only
./scripts/deploy_aws.sh frontend    # rebuild + redeploy the static export only
./scripts/deploy_aws.sh destroy     # tear it all down (8 → 7 → … → 1, plus ECR)
```

`destroy` schedules the CMK for 7-day deletion (the AWS minimum); to recover within that window, `aws kms cancel-key-deletion --key-id alias/devforge-secrets`.

### Common deploy errors

- **`AccessDeniedException: Access to KMS is not allowed`** during step 1 — your IAM user is missing `kms:CreateGrant` on the new CMK. The key policy in `1_permissions/main.tf` already includes it for the deploying caller; if you used Path B (admin-pre-creates-CMK), have the admin add `CreateGrant` to your key-policy entry.
- **`column "clerk_user_id" already exists`** during step 3 — fixed in `run_migrations.py:apply_aws()`. If you're on an older revision, rerun against an empty Aurora.
- **`PageNotFoundError: Cannot find module for page: /jobs/123`** on the deployed frontend — the static export is missing the dynamic route's chunk. Check `frontend/out/jobs/[id].html` exists; if not, `npm run build` failed silently. Re-run `make rebuild` locally first.
- **`AccessDenied` on `aws s3 sync` during step 7** — your CLI creds need `s3:PutObject` on the new bucket. The bucket policy only grants CloudFront's OAC; you also need IAM perms on the user.

## Threat model

Four layers protect every destructive action:

1. **Pre-flight ticket secret scan** (`backend/safety/secret_redact.py`): every ticket title + body is scanned for live-shaped credentials (Stripe, OpenAI, Anthropic, GitHub, AWS, Slack, JWT, PEM, GCP — 14 families). Any hit rejects the run before any agent executes — zero LLM cost, zero side effects.
2. **Denylist** (`backend/safety/denylist.py`): catastrophic ops (`rm -rf /`, `DROP TABLE`, `git push --force`) are refused outright. Destructive ops (migrations, dependency bumps, infra) require an approval token.
3. **Approval tokens** (`backend/safety/approval.py`): 5-minute TTL, one-time use, SHA-256-bound to the `approval_command` string (ticket-bound — survives across job_id rotations). The orchestrator sweeps prior `awaiting_approval` jobs for the same command on consume so they fall off the queue.
4. **Scope enforcement** (`backend/safety/scope.py` + fs-mcp): every filesystem access resolves under the worktree root; escapes raise `PathOutOfScope`. Egress allowlist applied on AWS.

Plus:
- **Prompt-injection scrub** on ticket bodies + RAG content (READMEs, issue text) — fenced as `[UNTRUSTED CONTENT]` with high-signal triggers redacted.
- **PR-only merge gate**: `git_push` rejects `main`-targeted pushes; QA opens PRs but never merges.
- **GitHub App scoped per-repo**: Contents:write only on non-`main` refs; tokens minted per-job, 60-min TTL.
- **Control plane dual-auth**: every gated endpoint accepts a Clerk JWT (browser) OR an admin token (CLI). Browser-facing admin operations (`POST /approvals/run`) authorize via Clerk JWT against `tenants.clerk_user_id` / `clerk_org_id` — no admin secret ever leaves the server.
- **Customer-managed KMS** (`alias/devforge-secrets`): both Secrets Manager entries (OpenRouter key, GitHub App PEM) are encrypted with a CMK provisioned by `terraform/1_permissions`. Annual rotation is on; the consumer roles get scoped `kms:Decrypt` via a `kms:ViaService` condition so the key can only decrypt through Secrets Manager. Path B (admin pre-creates the key, you pass `var.kms_cmk_arn`) is supported for environments where the deploying user lacks `kms:CreateKey`.

## TODO v2 (v1 trade-offs)

- Egress allowlist on AWS is port-443-only via Security Group (not hostname-aware) — true allowlist needs AWS Network Firewall.
- Local mode has no OS-level egress enforcement; `is_host_allowed` is documentation, not a kernel filter.
- Single-tenant per repo, single-repo per tenant. Multi-repo fan-out is v2.
- Python + TS/JS only for AST chunking; other languages fall back to line-windows.
- Semgrep + detect-secrets in local mode; gitleaks binary in the Fargate Dockerfile (AWS).
- POST /jobs spawns `scripts.run_ticket` as a local subprocess. AWS deploy of ticket submission requires SQS dispatch (Lambda's 15-min ceiling won't survive a full crew run). The watch-only path (CLI submits, browser tails) is fully AWS-ready today.
- Frontend uses static export (no Next API routes / SSR / middleware). Future polish requiring SSR would need a runtime Next host (Vercel / Amplify).
