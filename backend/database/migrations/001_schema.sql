-- DevForge v1 schema — Day 3 slim.
-- Tables added Day 9+: approval_tokens (full), jobs.tokens, pr_links, events.

CREATE TABLE IF NOT EXISTS tenants (
    id                      BIGSERIAL PRIMARY KEY,
    name                    TEXT NOT NULL,
    github_owner            TEXT NOT NULL,
    github_installation_id  BIGINT NOT NULL UNIQUE,
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

CREATE TABLE IF NOT EXISTS jobs (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    repo_id         BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    ticket_title    TEXT NOT NULL,
    ticket_body     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued | running | awaiting_approval | pr_opened | failed
    pr_url          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approval_tokens (
    id              BIGSERIAL PRIMARY KEY,
    job_id          BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    command_sha256  TEXT NOT NULL,
    token_hash      TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT REFERENCES tenants(id) ON DELETE SET NULL,
    job_id      BIGINT REFERENCES jobs(id) ON DELETE SET NULL,
    actor       TEXT NOT NULL,              -- 'agent:backend', 'human:<clerk_id>', 'system'
    event       TEXT NOT NULL,              -- 'tool_call', 'approval_issued', 'pr_opened', ...
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_tenant  ON jobs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_job    ON audit_log(job_id, created_at DESC);
