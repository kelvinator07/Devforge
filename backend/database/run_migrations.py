"""Apply SQL migrations to the backend configured by DEVFORGE_BACKEND.

Local (SQLite) path — translates Postgres DDL on the fly.
AWS   (Aurora)  path — applies the SQL verbatim via rds-data:ExecuteStatement.

Run from repo root:
    uv run python -m backend.database.run_migrations
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from backend.common import get_backend
from backend.common.local_backend import SQLiteDB


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def translate_pg_to_sqlite(sql: str) -> str:
    """Rewrite the tiny subset of Postgres DDL we actually use so SQLite accepts it."""
    s = sql
    s = re.sub(r"\bBIGSERIAL PRIMARY KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", s)
    s = re.sub(r"\bBIGSERIAL\b", "INTEGER", s)
    s = re.sub(r"\bBIGINT\b", "INTEGER", s)
    s = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", s)
    s = re.sub(r"DEFAULT now\(\)", "DEFAULT CURRENT_TIMESTAMP", s)
    s = re.sub(r"\bJSONB\b", "TEXT", s)
    s = re.sub(r"::jsonb", "", s)
    return s


def split_sql(sql: str) -> list[str]:
    no_line_comments = re.sub(r"--[^\n]*", "", sql)
    return [s for s in no_line_comments.split(";") if s.strip()]


def _sqlite_drop_not_null(conn: sqlite3.Connection, table: str, column: str) -> None:
    """SQLite has no ALTER COLUMN DROP NOT NULL; rebuild the table.

    Preserves data, indexes, and the FK that points at jobs.id.
    """
    # Check whether the column still has NOT NULL — idempotent.
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    target = next((c for c in cols if c[1] == column), None)
    if target is None or target[3] == 0:  # notnull flag at index 3
        print(f"   (sqlite) {table}.{column}: already nullable, skipping")
        return

    # Inline rebuild: only known shape for approval_tokens. We reuse this
    # function for that one case; if more tables need it later, parameterize.
    if table != "approval_tokens" or column != "job_id":
        raise RuntimeError(
            f"sqlite drop-not-null only handles approval_tokens.job_id; got {table}.{column}"
        )

    print(f"   (sqlite) rebuilding {table} to drop NOT NULL on {column}")
    conn.executescript("""
        CREATE TABLE approval_tokens__new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id          INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
            command_sha256  TEXT NOT NULL,
            token_hash      TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            consumed_at     TEXT,
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO approval_tokens__new
            (id, job_id, command_sha256, token_hash, expires_at, consumed_at, created_at)
        SELECT id, job_id, command_sha256, token_hash, expires_at, consumed_at, created_at
        FROM approval_tokens;
        DROP TABLE approval_tokens;
        ALTER TABLE approval_tokens__new RENAME TO approval_tokens;
    """)


def apply_local(sql_files: list[Path]) -> None:
    backend = get_backend()
    if not isinstance(backend.db, SQLiteDB):
        raise RuntimeError("expected SQLiteDB for local path")
    db_path = backend.db.path
    print(f"   target: sqlite://{db_path}")
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for f in sql_files:
            print(f"== applying {f.name} (sqlite mode) ==")
            sql = translate_pg_to_sqlite(f.read_text())
            for stmt in split_sql(sql):
                preview = stmt.strip().splitlines()[0][:80]
                print(f"   > {preview}")
                # SQLite-only: synthesize the equivalent of ALTER COLUMN ... DROP NOT NULL.
                m = re.match(
                    r"\s*ALTER\s+TABLE\s+(\w+)\s+ALTER\s+COLUMN\s+(\w+)\s+DROP\s+NOT\s+NULL\s*",
                    stmt, re.IGNORECASE,
                )
                if m:
                    _sqlite_drop_not_null(conn, m.group(1), m.group(2))
                    continue
                conn.execute(stmt)
        conn.commit()


def apply_aws(sql_files: list[Path]) -> None:
    import boto3

    cluster_arn = os.environ["AURORA_CLUSTER_ARN"]
    secret_arn = os.environ["AURORA_SECRET_ARN"]
    database = os.environ.get("AURORA_DATABASE", "devforge")
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("rds-data", region_name=region)
    print(f"   target: aurora/{database} via rds-data")
    for f in sql_files:
        print(f"== applying {f.name} (postgres mode) ==")
        for stmt in split_sql(f.read_text()):
            print(f"   > {stmt.strip().splitlines()[0][:80]}")
            client.execute_statement(
                resourceArn=cluster_arn, secretArn=secret_arn,
                database=database, sql=stmt,
            )


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)

    mode = os.environ.get("DEVFORGE_BACKEND", "local")
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        raise SystemExit(f"no migrations found in {MIGRATIONS_DIR}")

    print(f"DEVFORGE_BACKEND={mode}")
    if mode == "local":
        apply_local(sql_files)
    elif mode == "aws":
        apply_aws(sql_files)
    else:
        raise SystemExit(f"unknown DEVFORGE_BACKEND: {mode!r}")
    print("all migrations applied.")


if __name__ == "__main__":
    main()
