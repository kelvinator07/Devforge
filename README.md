# DevForge

Enterprise multi-agent engineering platform — capstone project. A 4-agent crew (EngineeringLead, BackendEngineer, FrontendEngineer, QAEngineer) plans, implements, tests, and opens a PR for any well-specified ticket against a customer's GitHub repo, inside a sandboxed worktree with strict guardrails.

See `/Users/kelvini/Andela-LLM-Engineering/DevForge-openrouter.md` for the original 14-day build plan, `DEMO.md` for the 5-minute demo script, and `TESTING.md` for the runnable verification walkthrough.

## Status

Local-first with AWS deploy parity for every layer including the frontend. Ticket submission, one-click approval, live SSE event tail, LangFuse trace deep-link, multi-tenant scoping by Clerk identity, and S3+CloudFront frontend deploy all shipped.

| Concept | Where |
|---|---|
| **Agentic workflow** | 5 agents in `backend/worker/{lead,backend_engineer,frontend_engineer,migration_engineer,qa_engineer}.py` orchestrated by `backend/worker/orchestrator.py` |
| **Tool use** | `fs-mcp` + `sandbox-mcp` MCPs + `search_codebase` function-tool + `submit_for_review` PR-opener |
| **MCP** | 2 custom stdio MCPs in `backend/mcp/{fs_mcp,sandbox_mcp}/server.py` |
| **Guardrails** | `backend/safety/{denylist,injection_scrub,approval,scope,secret_redact}.py` — 4 layers: pre-flight ticket secret scan → denylist → approval-token → fs/egress scope |
| **Security** | Per-tenant GitHub App installs; sandbox in Fargate egress-allowlisted (AWS) or scope-checked (local); secrets in Secrets Manager (AWS) / env (local); audit log of every tool call; control plane dual-auth (Clerk JWT or admin token) |
| **RAG** | Per-tenant Chroma (local) / S3 Vectors (AWS) over AST-chunked code via `backend/ingest/chunker.py` + `index_tenant_repo.py` |
| **Embeddings** | SageMaker Serverless `all-MiniLM-L6-v2` (AWS) or `sentence-transformers` on CPU (local) — same model, same 384-dim output |
| **Observability** | LangFuse v4 cloud — single trace per job (Lead → Backend → QA spans) deep-linked from `/jobs/[id]` |

## Stack

- **LLM:** OpenRouter (per-agent model swap via `backend/worker/models.yaml`)
- **Agents framework:** OpenAI Agents SDK (`openai-agents`)
- **MCP:** Python `mcp` SDK with `MCPServerStdio`
- **Embeddings:** SageMaker Serverless / sentence-transformers
- **Vector store:** S3 Vectors / Chroma
- **Database:** Aurora Serverless v2 (Data API) / SQLite
- **Secrets:** AWS Secrets Manager / `.env.local` + `secrets/`
- **Static analysis:** Semgrep + detect-secrets (gitleaks-equivalent)
- **Testing:** pytest (backend, 106 unit tests across safety + ingest) + vitest (frontend, 9 unit tests for `lib/api.ts`)
- **Observability:** LangFuse v4 cloud (custom Agents-SDK → LangFuse exporter in `backend/worker/crew.py`)
- **Frontend:** Next.js 16 (Pages Router) + Tailwind v4 + Clerk v6 + `@microsoft/fetch-event-source` for header-authenticated SSE
- **Auth:** Clerk JWT for the dashboard, admin token for CLI tooling, dual-auth on every gated endpoint
- **Infra:** Terraform (6 independent modules) + Docker Desktop

## Architecture

A ticket flows from the browser to a 5-agent crew that plans, implements, tests, and ships a PR — all inside a sandboxed worktree. Local and AWS share the same code; only the dispatch shim and the storage adapters differ.

```mermaid
flowchart TB
    User([User])

    subgraph fe["Frontend &mdash; Next.js + Clerk"]
        Dash["/dashboard &middot; /jobs/(id) &middot; /approvals"]
    end

    subgraph cp["Control plane &mdash; FastAPI"]
        Routes["POST /jobs<br/>POST /approvals/run<br/>GET  /jobs/(id)/sse"]
        Auth["dual-auth: Clerk JWT or X-Admin-Token"]
        DB[("Aurora &middot; SQLite<br/>jobs &middot; job_events &middot;<br/>approval_tokens &middot; tenants")]
    end

    subgraph dispatch["Dispatch (DEVFORGE_BACKEND)"]
        Local["local: subprocess.Popen"]
        Aws["aws: ecs.run_task() &rarr; Fargate"]
    end

    subgraph worker["Worker &mdash; 5-agent crew + orchestrator"]
        Lead["Engineering Lead"]
        Eng["Backend / Frontend /<br/>Migration Engineer"]
        Qa["QA Engineer"]
        Mcps["fs-mcp &middot; sandbox-mcp<br/>(stdio MCP servers)"]
    end

    subgraph safety["SafetyGuard &mdash; 4 deterministic layers"]
        Sec["pre-flight secret scan<br/>(14 detector families)"]
        Den["denylist (catastrophic ops)"]
        Tok["approval tokens<br/>5-min TTL &middot; SHA-256 bound"]
        Sco["fs scope &middot; egress allowlist"]
    end

    subgraph rag["RAG"]
        Vec[("S3 Vectors &middot; Chroma")]
        Emb["SageMaker Serverless /<br/>sentence-transformers"]
    end

    subgraph ext["External services"]
        OR["OpenRouter LLM<br/>(per-agent model swap)"]
        Gh["GitHub App API<br/>(per-repo install)"]
        Lf["LangFuse v4<br/>(one trace per job)"]
    end

    User -->|sign in| Dash
    Dash -->|Bearer JWT| Routes
    Routes <--> Auth
    Routes <--> DB
    Routes -->|enqueue| dispatch
    Local --> worker
    Aws --> worker

    Lead --> Eng --> Qa
    Qa -->|tests pass| Gh

    Lead -.->|tool calls| Mcps
    Eng  -.->|tool calls| Mcps
    Qa   -.->|tool calls| Mcps

    Lead -.-> rag
    Eng  -.-> rag

    Lead -.->|inference| OR
    Eng  -.->|inference| OR
    Qa   -.->|inference| OR

    worker -.->|every span| Lf
    worker -.->|every step gated by| safety

    Routes <-->|SSE events| Dash
```

**Read it as request flow:**
1. User signs into the Next.js dashboard via Clerk; every API call carries a `Bearer` JWT.
2. `POST /jobs` (or `POST /approvals/run`) hits the dual-auth gate, persists a job row, and dispatches a worker — `subprocess.Popen` locally, `ecs.run_task()` on AWS. Same downstream code path either way.
3. The orchestrator runs the 5-agent crew through a single LangFuse trace: Lead plans → Engineers code (writes via fs-mcp, runs tests via sandbox-mcp) → QA tests → opens PR via the GitHub App.
4. Every step is intercepted by the four SafetyGuard layers: ticket secrets reject up front, a denylist refuses catastrophic ops, migrations and dep bumps require an approval token, and fs/egress are scope-checked.
5. The browser tails `/jobs/{id}/sse` for live events; the dashboard polls `/jobs?tenant_id=…` every 3s for job-list updates.

## Layout

```
backend/
  control_plane/   FastAPI on Lambda — tenant/jobs/approvals endpoints, SSE stream
  worker/          Crew + orchestrator. Runs locally as subprocess; on AWS as Fargate task.
    crew.py            — OpenRouter client + LangFuse v4 trace exporter
    schemas.py         — TaskPlan + StepKind enum + EngineerResult + QAResult
    lead.py            — EngineeringLead agent (structured output)
    backend_engineer.py
    frontend_engineer.py
    migration_engineer.py — staging-only DDL author
    qa_engineer.py
    orchestrator.py    — full crew driver + SSE-style event stream + supersede sweep
    worktree.py        — git worktree management
  ingest/          AST chunker + per-tenant codebase indexer
  mcp/             Custom MCP stdio servers
    fs_mcp/server.py     — read/write/list scoped to worktree
    sandbox_mcp/server.py — run_tests, run_coverage, run_semgrep, run_gitleaks
  safety/          SafetyGuard modules (deterministic, no LLM)
    secret_redact.py     — 14 detector families, used by ticket pre-flight + future log scrub
  cost/            OpenRouter usage tracker + dashboard CLI
  common/          Backend adapter (LocalBackend / AWSBackend) + admin_headers helper
  database/        Migrations + run_migrations.py with PG→SQLite translator
frontend/          Next.js 16 + Clerk + Tailwind v4 dashboard
  pages/
    dashboard.tsx      — tenant + recent jobs (3s poll, status filter, search)
    jobs/[id].tsx      — live SSE event timeline + LangFuse trace deep-link
    approvals.tsx      — pending approvals + Approve & run button
  lib/
    api.ts             — typed fetch wrapper + Clerk JWT attachment
    sse.ts             — fetch-event-source wrapper for header-auth SSE
  components/
    NewTicketModal.tsx, PendingApprovalCard.tsx, EventCard.tsx, StatusBadge.tsx
terraform/
  1_permissions/   Secrets Manager (OpenRouter key, GitHub App PEM) + IAM policy + CMK
  2_sagemaker/     Embedding endpoint
  3_database/      Aurora Serverless v2 with Data API
  4_worker/        ECS Fargate + 443-only egress SG
  5_control_plane/ Control plane Lambda + HTTP API
  6_frontend/      S3 + CloudFront (OAC, SPA fallback) for the static-export Next app
tests/
  conftest.py            — sys.path setup + tmp_db fixture (per-test SQLite + migrations)
  safety/                — test_secret_redact, test_denylist, test_approval (92 tests)
  ingest/                — test_chunker (14 tests)
frontend/lib/api.test.ts — vitest suite for fetch wrappers + URL builders
scripts/
  local_dev.sh           — setup | serve | smoke | onboard
  deploy_aws.sh          — all | <module> | frontend | destroy
  populate_demo_repo.py  — seed the demo FastAPI app via the GitHub App
  index_repo.py          — chunk + embed a tenant's codebase
  search_codebase.py     — semantic search CLI
  run_ticket.py          — full crew E2E with SSE-line stdout (DEVFORGE_JOB_ID-aware)
  mint_approval.py       — issue an approval token for a destructive job
  link_tenant_clerk_identity.py — backfill tenants.clerk_user_id / clerk_org_id
  supersede_stale_approvals.py  — one-shot cleanup of pre-supersede awaiting_approval rows
  redteam.py             — 9 deterministic guardrail tests (pass/fail report)
  verify_mcps.py         — MCP smoke harness
```

## Quickstart (local — Docker + Makefile)

The local stack runs in two containers: control plane (FastAPI on :8001) and frontend (Next.js on :3000). Workers spawn as subprocesses inside the control-plane container per ticket. Source is bind-mounted for hot-reload edit `backend/`, `scripts/`, or `frontend/` and the running stack picks it up.

```bash
cd devforge
cp .env.example .env.local                       # edit: OPENROUTER_API_KEY, GITHUB_APP_*, DEVFORGE_ADMIN_TOKEN, CLERK_JWKS_URL
cp frontend/.env.example frontend/.env.local     # edit: NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, etc.

make setup        # build images, install deps, run migrations (one-time)
make dev          # control-plane :8001 + frontend :3000

# One-time: link tenant 1 to your Clerk user (so /tenants/me resolves)
make shell
> uv run python -m scripts.link_tenant_clerk_identity 1 --user user_<your-id>
> exit

make seed         # populate + index the demo GitHub repo (one-time)
make ticket       # run the default demo ticket E2E through the crew
make test         # 106 pytest + 9 vitest unit tests, ~3s, $0
make redteam      # 9/9 deterministic guardrails, $0
make cost         # per-job cost dashboard
make logs         # tail both services
make stop         # graceful shutdown
make clean        # wipe volumes + data/
```

`make help` lists every target.

### Unit tests

```bash
make test           # both suites
make test-backend   # uv run pytest -q
make test-frontend  # cd frontend && npm test (vitest)
```

Coverage targets the safety-critical primitives whose regressions cause silent damage:

| Module | Tests | What's covered |
|---|---|---|
| `backend/safety/secret_redact.py` | 43 | 14 detector families × scan + redact + false-positive guards |
| `backend/safety/denylist.py` | 40 | 3-tier classifier (safe/destructive/catastrophic) + plan-step path |
| `backend/safety/approval.py` | 9 | mint/verify round-trip, one-time use, TTL, command-swap, strict job scoping |
| `backend/ingest/chunker.py` | 14 | Python AST + JS heuristic + line-window fallback + repo walk skip rules |
| `frontend/lib/api.ts` | 9 | fetch wrappers, JWT attachment, 422 secret-rejection surfacing, URL builders |

Pytest fixtures (`tests/conftest.py`) provide a per-test SQLite at `tmp_path/devforge.db` with all migrations applied — no test ever touches the dev DB.

> **Non-Docker fallback:** the original `./scripts/local_dev.sh` flow is still supported for power users who want the host's `uv` + `npm` directly. 
> Run `./scripts/local_dev.sh setup && ./scripts/local_dev.sh serve` and start `cd frontend && npm run dev` in another terminal.
> `Makefile` is the documented path going forward; `local_dev.sh` is preserved.

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
