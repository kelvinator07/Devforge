"""Scope checks shared by the orchestrator.

fs-mcp already enforces filesystem scope at the tool boundary. This module
exists so non-MCP code paths (indexer, commit_and_push, direct worktree ops)
can reuse the same check. Also hosts the egress allowlist for tools that
make HTTP calls from outside a Fargate sandbox.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


# Allowed hosts for outbound HTTP from worker code running on AWS Fargate.
# On local dev we don't enforce this (no way to block at OS level without
# Network Firewall); document it instead.
EGRESS_ALLOWLIST = {
    "api.github.com",
    "codeload.github.com",
    "uploads.github.com",
    "openrouter.ai",
    "cloud.langfuse.com",
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    # AWS service endpoints inside the VPC resolve via VPC endpoints; not
    # included here because those are hostnames like runtime.sagemaker.us-east-1.amazonaws.com
}


def ensure_path_in_scope(path: Path | str, root: Path | str) -> Path:
    """Raise ValueError('PathOutOfScope') if `path` escapes `root`."""
    root_p = Path(root).resolve()
    candidate = (root_p / str(path).lstrip("/")).resolve()
    try:
        candidate.relative_to(root_p)
    except ValueError:
        raise ValueError(f"PathOutOfScope: {path!r} escapes root {root_p}")
    return candidate


def is_host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in EGRESS_ALLOWLIST or any(
        host.endswith("." + allowed) for allowed in EGRESS_ALLOWLIST
    )
