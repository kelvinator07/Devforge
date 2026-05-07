-- Per-repo RAG indexing as a first-class job.
--
-- index_jobs tracks one indexing run per (tenant, repo). The dedicated
-- index_job_events table mirrors job_events shape so the same SSE generator
-- pattern can stream progress to the frontend setup page. Kept separate
-- from job_events to avoid relaxing job_events.job_id NOT NULL (which the
-- local SQLite migration runner doesn't generically support).

CREATE TABLE IF NOT EXISTS index_jobs (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    repo_id         BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'queued',
    -- queued | running | completed | failed
    files_indexed   INTEGER,
    chunks_written  INTEGER,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_index_jobs_repo
    ON index_jobs(repo_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_index_jobs_tenant
    ON index_jobs(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS index_job_events (
    id              BIGSERIAL PRIMARY KEY,
    index_job_id    BIGINT NOT NULL REFERENCES index_jobs(id) ON DELETE CASCADE,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event           TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_index_job_events_job
    ON index_job_events(index_job_id, ts);
