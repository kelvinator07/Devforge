"""Run an indexing job that the control plane pre-created.

Usage:
    uv run python -m scripts.run_index_job <index_job_id>

Loads the index_jobs row, mints a fresh GitHub App installation token, calls
`backend.ingest.index_tenant_repo.index_repo` with an `on_event` callback that
writes phase events into `index_job_events`, and updates `index_jobs.status`
to completed/failed at the end. The frontend setup page subscribes to those
events via SSE.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)


def _emit(db, index_job_id: int, event: str, payload: dict) -> None:
    try:
        db.execute(
            "INSERT INTO index_job_events (index_job_id, event, payload) "
            "VALUES (:i, :e, :p)",
            {"i": index_job_id, "e": event, "p": json.dumps(payload)},
        )
    except Exception as exc:
        # Never let observability crash the run.
        print(f"[run_index_job] event_persist_failed: {exc}", flush=True)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: run_index_job.py <index_job_id>")
    try:
        index_job_id = int(sys.argv[1])
    except ValueError:
        sys.exit("index_job_id must be an integer")

    from backend.common import get_backend

    db = get_backend().db

    rows = db.execute(
        "SELECT tenant_id, repo_id FROM index_jobs WHERE id = :i",
        {"i": index_job_id},
    )
    if not rows:
        sys.exit(f"index_job {index_job_id} not found")
    tenant_id = rows[0]["tenant_id"]
    repo_id = rows[0]["repo_id"]

    repo_rows = db.execute(
        "SELECT full_name FROM repos WHERE id = :r", {"r": repo_id},
    )
    if not repo_rows:
        sys.exit(f"repo {repo_id} not found")
    repo_full_name = repo_rows[0]["full_name"]

    tenant_rows = db.execute(
        "SELECT github_installation_id FROM tenants WHERE id = :t",
        {"t": tenant_id},
    )
    if not tenant_rows:
        sys.exit(f"tenant {tenant_id} not found")
    installation_id = tenant_rows[0]["github_installation_id"]

    db.execute(
        "UPDATE index_jobs SET status='running', started_at=CURRENT_TIMESTAMP "
        "WHERE id = :i",
        {"i": index_job_id},
    )
    _emit(db, index_job_id, "index_started", {
        "tenant_id": tenant_id,
        "repo_id": repo_id,
        "repo": repo_full_name,
    })

    try:
        from backend.control_plane.github_app import installation_token_for
        from backend.ingest.index_tenant_repo import index_repo

        app_id = os.environ.get("GITHUB_APP_ID")
        if not app_id:
            raise RuntimeError("GITHUB_APP_ID is not configured")
        token, _expires = installation_token_for(app_id, installation_id)
        _emit(db, index_job_id, "token_minted", {})

        stats = index_repo(
            tenant_id,
            repo_full_name,
            token,
            on_event=lambda ev, payload: _emit(db, index_job_id, ev, payload),
        )

        db.execute(
            "UPDATE index_jobs SET status='completed', "
            "finished_at=CURRENT_TIMESTAMP, "
            "files_indexed=:f, chunks_written=:c WHERE id = :i",
            {
                "i": index_job_id,
                "f": stats["files_indexed"],
                "c": stats["chunks_written"],
            },
        )
        _emit(db, index_job_id, "index_done", {
            "ok": True,
            "files_indexed": stats["files_indexed"],
            "chunks_written": stats["chunks_written"],
        })
        print(f"[run_index_job] {index_job_id}: completed", flush=True)
    except Exception as exc:
        msg = str(exc)[:500]
        db.execute(
            "UPDATE index_jobs SET status='failed', "
            "finished_at=CURRENT_TIMESTAMP, error=:e WHERE id = :i",
            {"i": index_job_id, "e": msg},
        )
        _emit(db, index_job_id, "index_failed", {"error": msg})
        print(f"[run_index_job] {index_job_id}: failed — {msg}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
