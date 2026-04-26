"""Tests for backend.safety.approval — mint/verify_and_consume round-trip.

Uses the `tmp_db` fixture (per-test SQLite at tmp_path) so each test
gets a fresh approval_tokens table seeded by the real migrations.
"""
from __future__ import annotations

import pytest


def test_mint_returns_raw_token(tmp_db) -> None:
    from backend.safety.approval import mint

    raw = mint(command="run_job:1:DEMO-1:Test ticket")
    assert isinstance(raw, str)
    # token_urlsafe(32) yields ~43 chars; anything notably shorter is suspicious.
    assert len(raw) > 20


def test_verify_and_consume_happy_path(tmp_db) -> None:
    from backend.safety.approval import mint, verify_and_consume

    cmd = "run_job:1:DEMO-1:Test ticket"
    raw = mint(command=cmd)
    assert verify_and_consume(command=cmd, token_raw=raw) is True


def test_verify_consumes_once(tmp_db) -> None:
    """Second consume must fail: tokens are one-time use."""
    from backend.safety.approval import mint, verify_and_consume

    cmd = "run_job:1:DEMO-1:once"
    raw = mint(command=cmd)
    assert verify_and_consume(command=cmd, token_raw=raw) is True
    assert verify_and_consume(command=cmd, token_raw=raw) is False


def test_verify_rejects_wrong_command(tmp_db) -> None:
    """Tokens are SHA-256-bound to the command — swapping the command fails."""
    from backend.safety.approval import mint, verify_and_consume

    raw = mint(command="run_job:1:DEMO-1:original")
    assert (
        verify_and_consume(command="run_job:1:DEMO-1:tampered", token_raw=raw)
        is False
    )


def test_verify_rejects_expired(tmp_db, monkeypatch) -> None:
    """TTL=0 means the token is already expired by the time we verify."""
    monkeypatch.setenv("DEVFORGE_APPROVAL_TTL_SEC", "0")
    from backend.safety.approval import mint, verify_and_consume

    cmd = "run_job:1:DEMO-1:expired"
    raw = mint(command=cmd)
    assert verify_and_consume(command=cmd, token_raw=raw) is False


def test_verify_rejects_garbage_token(tmp_db) -> None:
    from backend.safety.approval import mint, verify_and_consume

    # Plant a real token to make sure the table isn't empty.
    mint(command="run_job:1:DEMO-1:Test")
    assert (
        verify_and_consume(command="run_job:1:DEMO-1:Test", token_raw="not-a-real-token")
        is False
    )


def test_verify_rejects_when_no_tokens(tmp_db) -> None:
    """Verifying against an empty table must fail cleanly (not crash)."""
    from backend.safety.approval import verify_and_consume

    assert (
        verify_and_consume(command="run_job:1:DEMO-1:nothing", token_raw="anything")
        is False
    )


def test_strict_job_id_scoping(tmp_db) -> None:
    """A token minted for job_id=42 should only verify with that job_id (or None)."""
    from backend.safety.approval import mint, verify_and_consume

    cmd = "run_job:1:DEMO-1:strict"
    raw = mint(job_id=42, command=cmd)
    # Mismatched job_id must fail.
    assert verify_and_consume(job_id=99, command=cmd, token_raw=raw) is False
    # Matching job_id (or omitted) succeeds.
    assert verify_and_consume(job_id=42, command=cmd, token_raw=raw) is True


def test_list_pending_excludes_consumed(tmp_db) -> None:
    from backend.safety.approval import list_pending, mint, verify_and_consume

    raw = mint(command="run_job:1:DEMO-1:listed")
    pending = list_pending()
    assert any(row["consumed_at"] is None for row in pending)

    verify_and_consume(command="run_job:1:DEMO-1:listed", token_raw=raw)
    pending_after = list_pending()
    # The token we just consumed should no longer appear.
    assert all(row["token_hash"] != raw for row in pending_after if "token_hash" in row)
