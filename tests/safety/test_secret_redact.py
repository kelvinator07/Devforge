"""Tests for backend.safety.secret_redact: scan + redact across 14 detectors.

Each detector family gets a positive case (the literal value is fake but
shape-matches a real key) plus a few negatives to catch false positives.
"""
from __future__ import annotations

import pytest

from backend.safety.secret_redact import redact_secrets, scan_secrets

# (kind, sample text containing a shape-matched fake secret)
POSITIVES = [
    ("STRIPE_SECRET", "STRIPE_KEY = sk_live_4eC39HqLyjWDarjtT1zdp7dc12345678"),
    ("STRIPE_SECRET", "sk_test_4eC39HqLyjWDarjtT1zdp7dc12345678 in body"),
    ("STRIPE_RESTRICTED", "rk_live_4eC39HqLyjWDarjtT1zdp7dc12345678"),
    ("STRIPE_PUBLISHABLE", "pk_live_4eC39HqLyjWDarjtT1zdp7dc12345678"),
    ("OPENAI", "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"),
    ("ANTHROPIC", "key sk-ant-api01-mzhdyourrealtokenhere1234567890abcdef"),
    ("OPENROUTER", "sk-or-v1-1234567890abcdefghijklmnopqrstuvwxyz0123"),
    ("GITHUB_PAT", "ghp_1234567890abcdefghijklmnopqrstuvwxyz"),
    ("GITHUB_INSTALL", "Bearer ghs_1234567890abcdefghijklmnopqrstuvwxyz"),
    ("GITHUB_OAUTH", "gho_1234567890abcdefghijklmnopqrstuvwxyz"),
    ("AWS_ACCESS_KEY", "aws_access_key_id=AKIAIOSFODNN7EXAMPLE"),
    ("AWS_ACCESS_KEY", "ASIA1234567890ABCDEF temp creds"),
    ("SLACK", "slack=xoxb-1234567890-abcdefghijkl"),
    ("JWT", "Authorization: Bearer eyJhbGciOiJI.eyJzdWIiOiI.SflKxwRJSMeKKF"),
    ("PRIVATE_KEY",
     "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"),
    ("GCP_API", "AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R"),
]

CLEAN_TEXTS = [
    "hello world, no secrets here.",
    "def my_function(): return 'hello'",
    "https://example.com/path?q=v",
    "the user's password is hunter2 (don't store this for real)",
    # Looks vaguely token-shaped but isn't any specific format.
    "session_id=abcd1234efgh5678",
]


@pytest.mark.parametrize("kind,sample", POSITIVES)
def test_scan_detects_kind(kind: str, sample: str) -> None:
    hits = scan_secrets(sample)
    assert any(h[0] == kind for h in hits), \
        f"expected {kind} in {hits!r}"


@pytest.mark.parametrize("kind,sample", POSITIVES)
def test_redact_replaces_kind(kind: str, sample: str) -> None:
    cleaned, kinds = redact_secrets(sample)
    assert kind in kinds
    assert f"[REDACTED-{kind}]" in cleaned


def test_scan_empty_string() -> None:
    assert scan_secrets("") == []


def test_scan_none_safe() -> None:
    # The function guards against None even though the type hint forbids it.
    assert scan_secrets(None) == []  # type: ignore[arg-type]


@pytest.mark.parametrize("text", CLEAN_TEXTS)
def test_clean_text_no_false_positive(text: str) -> None:
    assert scan_secrets(text) == []


def test_redact_idempotent_on_clean_text() -> None:
    cleaned, kinds = redact_secrets("hello world")
    assert cleaned == "hello world"
    assert kinds == []


def test_snippet_starts_with_safe_prefix() -> None:
    """The (kind, snippet) tuple's snippet should be the deterministic prefix
    every key of that family shares (e.g. 'sk_live_'), not the random tail."""
    hits = scan_secrets("token=sk_live_4eC39HqLyjWDarjtT1zdp7dc12345678")
    assert hits, "expected at least one hit"
    kind, snippet = hits[0]
    assert kind == "STRIPE_SECRET"
    assert snippet.startswith("sk_live_")
    assert snippet.endswith("…")


def test_multiple_kinds_in_one_text() -> None:
    text = (
        "stripe=sk_live_4eC39HqLyjWDarjtT1zdp7dc12345678 "
        "github=ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    )
    hits = scan_secrets(text)
    kinds = {k for k, _ in hits}
    assert "STRIPE_SECRET" in kinds
    assert "GITHUB_PAT" in kinds


def test_redact_preserves_surrounding_text() -> None:
    cleaned, _ = redact_secrets("before sk_live_4eC39HqLyjWDarjtT1zdp7dc12345678 after")
    assert cleaned.startswith("before ")
    assert cleaned.endswith(" after")
    assert "sk_live_" not in cleaned
