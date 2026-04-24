-- Day 10: persist orchestrator events so the (future) frontend can replay them.
-- Written in Postgres flavor; run_migrations.py translates to SQLite for local dev.

CREATE TABLE IF NOT EXISTS job_events (
    id            BIGSERIAL PRIMARY KEY,
    job_id        BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    event         TEXT NOT NULL,
    payload       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, ts);
