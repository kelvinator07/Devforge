"""Redact secret-shaped strings from arbitrary text.

Used at the boundaries that EGRESS user-supplied text (ticket body, ticket
title) to anywhere outside the trusted runtime — most importantly:

  - PR body / PR title (visible on GitHub remote)
  - jobs.ticket_body / jobs.ticket_title persisted in the DB and returned
    by /jobs/{id} to anyone with read access
  - SSE event payloads

Agents themselves receive the UNREDACTED text — they need to understand the
request to refuse it. The agent's own sanitization (rewriting `sk_live_…`
to a placeholder) is independent.

Patterns cover the most common providers. Anything matched is replaced with
`[REDACTED-<KIND>]`. Returns the cleaned text plus the list of kinds redacted.
"""
from __future__ import annotations

import re


_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Stripe — live, test, restricted, oauth.
    (re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{16,}"), "STRIPE_SECRET"),
    (re.compile(r"\brk_(live|test)_[A-Za-z0-9]{16,}"), "STRIPE_RESTRICTED"),
    (re.compile(r"\bpk_(live|test)_[A-Za-z0-9]{16,}"), "STRIPE_PUBLISHABLE"),
    # OpenAI / Anthropic / OpenRouter.
    (re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{20,}"), "OPENAI"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "ANTHROPIC"),
    (re.compile(r"\bsk-or-[vV]\d-[A-Za-z0-9]{20,}"), "OPENROUTER"),
    (re.compile(r"\bsk-[A-Za-z0-9]{30,}"), "OPENAI_LEGACY"),
    # GitHub tokens.
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "GITHUB_PAT"),
    (re.compile(r"\bghs_[A-Za-z0-9]{30,}"), "GITHUB_INSTALL"),
    (re.compile(r"\bgho_[A-Za-z0-9]{30,}"), "GITHUB_OAUTH"),
    (re.compile(r"\bghu_[A-Za-z0-9]{30,}"), "GITHUB_USER"),
    (re.compile(r"\bghr_[A-Za-z0-9]{30,}"), "GITHUB_REFRESH"),
    # AWS access / temporary keys.
    (re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASCA)[A-Z0-9]{16}"),
     "AWS_ACCESS_KEY"),
    # Slack.
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "SLACK"),
    # JWT-shaped (header.payload.signature, base64url).
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
     "JWT"),
    # PEM-encoded private keys (multi-line, single-line forms).
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
     "PRIVATE_KEY"),
    # Google Cloud / Firebase service-account keys often start with this.
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"), "GCP_API"),
]


def scan_secrets(text: str) -> list[tuple[str, str]]:
    """Return [(kind, safe_prefix_snippet), ...] for every secret-shaped match.

    Used by the orchestrator's pre-flight rejection gate. The snippet is the
    first ~8 chars of the matched value followed by `…` — safe to log because
    it's the deterministic prefix every key of that family shares (e.g.
    `sk_live_`, `ghp_`, `AKIA`), not the random secret tail. Empty list
    means the text is clean.
    """
    if not text:
        return []
    out: list[tuple[str, str]] = []
    for pat, kind in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            head = m.group(0)[:8]
            out.append((kind, f"{head}…"))
    return out


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Replace each matched secret with [REDACTED-<KIND>]. Returns (cleaned, kinds_seen)."""
    if not text:
        return text, []
    seen: list[str] = []
    cleaned = text
    for pat, kind in _SECRET_PATTERNS:
        if pat.search(cleaned):
            seen.append(kind)
            cleaned = pat.sub(f"[REDACTED-{kind}]", cleaned)
    return cleaned, seen
