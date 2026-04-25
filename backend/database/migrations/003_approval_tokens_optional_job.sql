-- Tier-2 fix: ticket-bound approval tokens can be minted before any job exists.
-- Drop the NOT NULL on approval_tokens.job_id and let it be NULL for command-only
-- (ticket-bound) tokens. The FK stays so explicitly-job-bound tokens still cascade.
--
-- Postgres path: ALTER COLUMN ... DROP NOT NULL.
-- SQLite path: rebuild the table since SQLite can't drop NOT NULL in place.

-- Postgres-flavored — run_migrations.py rewrites for SQLite at apply time.
ALTER TABLE approval_tokens ALTER COLUMN job_id DROP NOT NULL;
