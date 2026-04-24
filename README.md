# DevForge

Enterprise multi-agent engineering platform — capstone project. A 4-agent crew (EngineeringLead, BackendEngineer, FrontendEngineer, QAEngineer) plans, implements, tests, and opens a PR for any well-specified ticket against a customer's GitHub repo, inside a sandboxed worktree with strict guardrails.

See `/Users/kelvini/Andela-LLM-Engineering/DevForge-openrouter.md` for the original 14-day build plan and `DEMO.md` for the 5-minute demo script.

## Status

**Days 1–14 complete.** Local-first with AWS deploy parity. Frontend (Next.js + Clerk) deferred to a follow-up session — the orchestrator currently emits SSE-style JSON-line events on stdout for terminal use.

| Concept | Where |
|---|---|
| **Agentic workflow** | 4 agents in `backend/worker/{lead,backend_engineer,frontend_engineer,qa_engineer}.py` orchestrated by `backend/worker/orchestrator.py` |
| **Tool use** | `fs-mcp` + `sandbox-mcp` MCPs + `search_codebase` function-tool + `submit_for_review` PR-opener |
| **MCP** | 2 custom stdio MCPs in `backend/mcp/{fs_mcp,sandbox_mcp}/server.py` |
| **Guardrails** | `backend/safety/{denylist,injection_scrub,approval,scope}.py` — 3 layers: denylist → approval-token → fs/egress scope |
| **Security** | Per-tenant GitHub App installs; sandbox in Fargate egress-allowlisted (AWS) or scope-checked (local); secrets in Secrets Manager (AWS) / env (local); audit log of every tool call |
| **RAG** | Per-tenant Chroma (local) / S3 Vectors (AWS) over AST-chunked code via `backend/ingest/chunker.py` + `index_tenant_repo.py` |
| **Embeddings** | SageMaker Serverless `all-MiniLM-L6-v2` (AWS) or `sentence-transformers` on CPU (local) — same model, same 384-dim output |

## Stack

- **LLM:** OpenRouter (per-agent model swap via `backend/worker/models.yaml`)
- **Agents framework:** OpenAI Agents SDK (`openai-agents`)
- **MCP:** Python `mcp` SDK with `MCPServerStdio`
- **Embeddings:** SageMaker Serverless / sentence-transformers
- **Vector store:** S3 Vectors / Chroma
- **Database:** Aurora Serverless v2 (Data API) / SQLite
- **Secrets:** AWS Secrets Manager / `.env.local` + `secrets/`
- **Static analysis:** Semgrep + detect-secrets (gitleaks-equivalent)
- **Observability (optional):** LangFuse cloud
- **Infra:** Terraform (7 independent modules) + Docker Desktop

## Layout

```
backend/
  control_plane/   FastAPI on Lambda — tenant onboarding + approval endpoints
  worker/          Crew + orchestrator. Runs locally as subprocess; on AWS as Fargate task.
    crew.py            — OpenRouter client + LangFuse tracing wiring
    schemas.py         — TaskPlan + StepKind enum + EngineerResult + QAResult
    lead.py            — EngineeringLead agent (structured output)
    backend_engineer.py
    frontend_engineer.py
    qa_engineer.py
    orchestrator.py    — full crew driver + SSE-style event stream
    worktree.py        — git worktree management
  ingest/          AST chunker + per-tenant codebase indexer
  mcp/             Custom MCP stdio servers
    fs_mcp/server.py     — read/write/list scoped to worktree
    sandbox_mcp/server.py — run_tests, run_coverage, run_semgrep, run_gitleaks
  safety/          SafetyGuard modules (deterministic, no LLM)
  cost/            OpenRouter usage tracker + dashboard CLI
  common/          Backend adapter (LocalBackend / AWSBackend)
  database/        Migrations + run_migrations.py with PG→SQLite translator
frontend/          (deferred — Next.js + Clerk)
terraform/
  1_permissions/   Secrets Manager (OpenRouter key, GitHub App PEM) + IAM policy
  2_sagemaker/     Embedding endpoint
  3_ingestion/     S3 Vectors + ingest Lambda + API Gateway
  5_database/      Aurora Serverless v2 with Data API
  6_worker/        ECS Fargate + 443-only egress SG
  7_control_plane/ Control plane Lambda + HTTP API
scripts/
  local_dev.sh           — setup | serve | smoke | onboard
  deploy_aws.sh          — all | <module> | destroy
  populate_demo_repo.py  — seed the demo FastAPI app via the GitHub App
  index_repo.py          — chunk + embed a tenant's codebase
  search_codebase.py     — semantic search CLI
  run_ticket.py          — full crew E2E with SSE-line stdout
  mint_approval.py       — issue an approval token for a destructive job
  redteam.py             — 8 deterministic guardrail tests (pass/fail report)
  verify_mcps.py         — MCP smoke harness
```

## Quickstart (local)

```bash
cd devforge
cp .env.example .env.local           # edit: OPENROUTER_API_KEY, GITHUB_APP_*
./scripts/local_dev.sh setup
./scripts/local_dev.sh serve         # terminal A: control plane on :8001

# terminal B (one-time):
uv run python -m scripts.populate_demo_repo 1
uv run python -m scripts.index_repo 1

# Run a ticket through the crew:
uv run python -m scripts.run_ticket 1 | tee /tmp/run.log

# Verify guardrails:
uv run python -m scripts.redteam

# Cost dashboard:
uv run python -m backend.cost.dashboard --tenant 1
```

See `DEMO.md` for the full 5-minute demo flow with the 3 killer guardrail moments.

## Push to AWS

```bash
./scripts/deploy_aws.sh all          # full Day 1-3 deploy
./scripts/deploy_aws.sh worker       # just rebuild + push the worker image
./scripts/deploy_aws.sh destroy      # tear it all down
```

Environment auto-switches by `DEVFORGE_BACKEND=local|aws`. Same code in both modes; only the adapter implementations differ.

## Threat model

Three layers protect every destructive action:

1. **Denylist** (`backend/safety/denylist.py`): catastrophic ops (`rm -rf /`, `DROP TABLE`, `git push --force`) are refused outright. Destructive ops (migrations, dependency bumps, infra) require an approval token.
2. **Approval tokens** (`backend/safety/approval.py`): 5-minute TTL, one-time use, SHA-256-bound to the command — replay-resistant + swap-resistant. Minted via `scripts/mint_approval.py` (human-only — never exposed as an agent tool).
3. **Scope enforcement** (`backend/safety/scope.py` + fs-mcp): every filesystem access resolves under the worktree root; escapes raise `PathOutOfScope`. Egress allowlist applied on AWS.

Plus:
- **Prompt-injection scrub** on ticket bodies + RAG content (READMEs, issue text) — fenced as `[UNTRUSTED CONTENT]` with high-signal triggers redacted.
- **PR-only merge gate**: `git_push` rejects `main`-targeted pushes; QA opens PRs but never merges.
- **GitHub App scoped per-repo**: Contents:write only on non-`main` refs; tokens minted per-job, 60-min TTL.

## Not production-ready (v1 trade-offs)

- AWS-managed `aws/secretsmanager` KMS key (not customer-managed CMK) — `aiengineer` IAM user lacks `kms:CreateKey`.
- Egress allowlist on AWS is port-443-only via Security Group (not hostname-aware) — true allowlist needs AWS Network Firewall.
- Local mode has no OS-level egress enforcement; `is_host_allowed` is documentation, not a kernel filter.
- Frontend is CLI-only; Next.js + Clerk UI is deferred.
- Single-tenant per repo, single-repo per tenant. Multi-repo fan-out is v2.
- Python + TS/JS only for AST chunking; other languages fall back to line-windows.
- Semgrep + detect-secrets in local mode; gitleaks binary in the Fargate Dockerfile (AWS).
- No Clerk auth on the control plane yet; `/approve` endpoint is admin-API-key gated.

## Prerequisites

- AWS CLI configured (`aiengineer` IAM user) — only required for AWS-mode deploys
- Docker Desktop running — only required to build images for AWS push
- `uv` installed
- OpenRouter API key (https://openrouter.ai)
- GitHub App created (one-time setup; see DEMO.md)
