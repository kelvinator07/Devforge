-- DevForge schema (final state, squashed).
--
-- Replaces the earlier per-feature migration chain (001 schema, 002 job_events,
-- 003 approval_tokens.job_id NULLable, 004 tenants Clerk identity, 005 multi-
-- tenant indexes, 006 index_jobs). The runner is idempotent — every CREATE
-- uses IF NOT EXISTS and the script catches "duplicate column" — so this is
-- a no-op against existing populated DBs and a single-shot bootstrap on fresh
-- ones.
--
-- Postgres flavor; backend/database/run_migrations.py rewrites BIGSERIAL,
-- BIGINT, TIMESTAMPTZ, JSONB, and now() for SQLite at apply time.

-- ============================================================================
-- Core tenancy + GitHub install
-- ============================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id                      BIGSERIAL PRIMARY KEY,
    name                    TEXT NOT NULL,
    github_owner            TEXT NOT NULL,
    github_installation_id  BIGINT NOT NULL UNIQUE,
    clerk_user_id           TEXT,
    clerk_org_id            TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS repos (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    full_name       TEXT NOT NULL,
    default_branch  TEXT NOT NULL DEFAULT 'main',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, full_name)
);

-- ============================================================================
-- Ticket runs (the agent crew)
-- ============================================================================

CREATE TABLE IF NOT EXISTS jobs (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    repo_id         BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    ticket_title    TEXT NOT NULL,
    ticket_body     TEXT NOT NULL,
    -- queued | running | awaiting_approval | approval_superseded | pr_opened | failed | refused
    status          TEXT NOT NULL DEFAULT 'queued',
    pr_url          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_events (
    id            BIGSERIAL PRIMARY KEY,
    job_id        BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    event         TEXT NOT NULL,
    payload       TEXT NOT NULL DEFAULT '{}'
);

-- job_id is nullable so ticket-bound approval tokens can be minted before any
-- job exists. The FK still cascades for explicitly-job-bound tokens.
CREATE TABLE IF NOT EXISTS approval_tokens (
    id              BIGSERIAL PRIMARY KEY,
    job_id          BIGINT REFERENCES jobs(id) ON DELETE CASCADE,
    command_sha256  TEXT NOT NULL,
    token_hash      TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- Per-repo RAG indexing
-- ============================================================================

CREATE TABLE IF NOT EXISTS index_jobs (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    repo_id         BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    -- queued | running | completed | failed
    status          TEXT NOT NULL DEFAULT 'queued',
    files_indexed   INTEGER,
    chunks_written  INTEGER,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS index_job_events (
    id              BIGSERIAL PRIMARY KEY,
    index_job_id    BIGINT NOT NULL REFERENCES index_jobs(id) ON DELETE CASCADE,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event           TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}'
);

-- ============================================================================
-- Audit log
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT REFERENCES tenants(id) ON DELETE SET NULL,
    job_id      BIGINT REFERENCES jobs(id) ON DELETE SET NULL,
    actor       TEXT NOT NULL,              -- 'agent:backend', 'human:<clerk_id>', 'system'
    event       TEXT NOT NULL,              -- 'tool_call', 'approval_issued', 'pr_opened', ...
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_jobs_tenant
    ON jobs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_events_job
    ON job_events(job_id, ts);

CREATE INDEX IF NOT EXISTS idx_index_jobs_repo
    ON index_jobs(repo_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_index_jobs_tenant
    ON index_jobs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_index_job_events_job
    ON index_job_events(index_job_id, ts);

CREATE INDEX IF NOT EXISTS idx_audit_tenant
    ON audit_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_job
    ON audit_log(job_id, created_at DESC);

-- Non-unique lookup indexes — multiple tenants per Clerk identity are allowed
-- (one per GitHub App installation, e.g. personal + work).
CREATE INDEX IF NOT EXISTS idx_tenants_clerk_user_id
    ON tenants(clerk_user_id) WHERE clerk_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tenants_clerk_org_id
    ON tenants(clerk_org_id) WHERE clerk_org_id IS NOT NULL;
