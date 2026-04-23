# DevForge

Enterprise multi-agent engineering platform. See `/Users/kelvini/Andela-LLM-Engineering/DevForge-openrouter.md` for the full 14-day build plan.

## Status

Days 1–3 of the 14-day plan in progress. This repo is scaffolded but not yet functional.

## Stack

- **LLM:** OpenRouter (Claude Sonnet 4.6 / GPT-5 / Haiku 4.5 with fallback chain)
- **Embeddings:** SageMaker Serverless (`sentence-transformers/all-MiniLM-L6-v2`)
- **Infra:** AWS (Lambda / ECS Fargate / Aurora Serverless v2 / S3 Vectors / API Gateway / CloudFront)
- **Framework:** OpenAI Agents SDK

## Layout

```
backend/
  control_plane/   FastAPI on Lambda — job intake + approval endpoints
  worker/          ECS Fargate task — runs the 4-agent crew
  ingest/          Codebase + corpus indexer
  mcp/             Custom stdio MCPs (fs-mcp + sandbox-mcp)
  safety/          SafetyGuard — denylist, approval tokens, scope, scrub
  cost/            Per-job OpenRouter spend tracker + cap
  database/        Aurora schema + shared lib
frontend/          Next.js + Clerk dashboard
terraform/
  1_permissions/   IAM + KMS + secrets
  2_sagemaker/     Embedding endpoint
  3_ingestion/     S3 Vectors + ingest Lambda + API Gateway
  4_mcp/           MCP Lambda containers
  5_database/      Aurora
  6_worker/        ECS Fargate + egress allowlist
  7_control_plane/ Control-plane Lambda
  8_frontend/      CloudFront + S3 + API Gateway
  9_enterprise/    CloudWatch + LangFuse
scripts/           Onboarding + red-team + demo seeders
```

## Prerequisites

- AWS CLI configured (`aiengineer` IAM user)
- Docker Desktop running
- `uv` installed
- OpenRouter API key (https://openrouter.ai)
- GitHub App (created in Day 3)

## Deployment order

Terraform modules are independent; apply in numeric order on first deploy, each one reading outputs from the prior.
