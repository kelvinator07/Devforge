"""Approval tokens for destructive operations.

Tokens are:
  - 5-minute TTL (DEVFORGE_APPROVAL_TTL_SEC env override)
  - one-time use (consumed_at stamped on `verify`)
  - SHA-256-bound to the command text (swap-resistant)
  - stored hashed (raw token never persisted)

Tables (see backend/database/migrations/001_schema.sql):
  approval_tokens(id, job_id, command_sha256, token_hash, expires_at, consumed_at, created_at)
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.common import get_backend


def _ttl_sec() -> int:
    return int(os.environ.get("DEVFORGE_APPROVAL_TTL_SEC", "300"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cmd_hash(cmd: str) -> str:
    return hashlib.sha256(cmd.strip().encode("utf-8")).hexdigest()


def mint(*, job_id: int | None = None, command: str) -> str:
    """Create an approval token bound to `command` (and optionally to `job_id`).

    If `job_id` is None, the token is **command-bound only** — any future
    job whose orchestrator builds the same `approval_command` (typically
    `run_job:{tenant_id}:{ticket_id}:{ticket_title}`) will accept it. This
    is the right shape for human approval because every `run_ticket` call
    creates a fresh `jobs.id`, so a job-bound token would only ever be
    valid for the run that *just failed* and isn't rerunable.

    If `job_id` is provided, the token additionally binds to that job
    (used by tests + the redteam harness that want stricter scoping).
    """
    raw = secrets.token_urlsafe(32)
    get_backend().db.execute(
        """
        INSERT INTO approval_tokens (job_id, command_sha256, token_hash, expires_at)
        VALUES (:job, :ch, :th, :exp)
        """,
        {
            "job": job_id,  # NULL for ticket-bound tokens (post-migration 003)
            "ch": _cmd_hash(command),
            "th": _hash(raw),
            "exp": (_now() + timedelta(seconds=_ttl_sec())).isoformat(),
        },
    )
    return raw


def verify_and_consume(*, job_id: int | None = None, command: str, token_raw: str) -> bool:
    """Return True IFF an un-consumed, un-expired, matching token exists.

    Lookup is by command_sha256 + token_hash (NOT job_id) so a token minted
    for one run_ticket call can authorize the next attempt at the same
    ticket. Atomically marks the token consumed on first hit.

    `job_id` is accepted for backward compatibility but only used to scope
    the lookup when the stored token has a non-zero job_id (strict mode).
    Most callers should pass job_id=None or omit it.

    Any mismatch (wrong command, expired, consumed) returns False without
    leaking why.
    """
    ch = _cmd_hash(command)
    th = _hash(token_raw)
    # Command-bound lookup (the common case). If the token row has a stricter
    # job_id binding (>0) and the caller passed a job_id, enforce it.
    rows = get_backend().db.execute(
        """
        SELECT id, job_id, expires_at, consumed_at
        FROM approval_tokens
        WHERE command_sha256 = :ch AND token_hash = :th
        """,
        {"ch": ch, "th": th},
    )
    if not rows:
        return False
    row = rows[0]
    if row.get("consumed_at"):
        return False
    # Strict scoping: if the stored token was minted with a specific job_id
    # and the caller passed one, they must match.
    stored_job = row.get("job_id") or 0
    if stored_job > 0 and job_id is not None and stored_job != job_id:
        return False
    # expires_at is stored as ISO string or timestamp-with-tz depending on backend.
    exp_str = row["expires_at"]
    try:
        if isinstance(exp_str, str):
            exp_str = exp_str.replace(" ", "T").replace("+00:00", "+0000")
            exp = datetime.fromisoformat(exp_str.replace("+0000", "+00:00"))
        else:
            exp = exp_str
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    if exp < _now():
        return False
    get_backend().db.execute(
        "UPDATE approval_tokens SET consumed_at = :now WHERE id = :id",
        {"now": _now().isoformat(), "id": row["id"]},
    )
    return True


def list_pending(job_id: Optional[int] = None) -> list[dict]:
    """Read-only view for the eventual UI + for the red-team harness."""
    if job_id is None:
        return get_backend().db.execute(
            "SELECT id, job_id, command_sha256, expires_at, consumed_at FROM approval_tokens "
            "WHERE consumed_at IS NULL ORDER BY id DESC"
        )
    return get_backend().db.execute(
        "SELECT id, job_id, command_sha256, expires_at, consumed_at FROM approval_tokens "
        "WHERE job_id = :j AND consumed_at IS NULL ORDER BY id DESC",
        {"j": job_id},
    )
