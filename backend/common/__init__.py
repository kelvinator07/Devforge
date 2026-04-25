"""Backend adapter — switch between local dev and AWS with DEVFORGE_BACKEND env var.

Usage:

    from backend.common import get_backend

    backend = get_backend()
    rows = backend.db.execute("SELECT * FROM tenants")
    key = backend.secrets.get("openrouter-api-key")
    vec = backend.embedder.embed("hello")
    backend.vectors.put(index="devforge-kb", key="id1", vector=vec, metadata={"text": "hello"})
    hits = backend.vectors.query(index="devforge-kb", vector=vec, k=5)
"""
from __future__ import annotations

import os


def get_backend():
    mode = os.environ.get("DEVFORGE_BACKEND", "local").lower()
    if mode == "aws":
        from .aws_backend import AWSBackend
        return AWSBackend()
    if mode == "local":
        from .local_backend import LocalBackend
        return LocalBackend()
    raise ValueError(f"DEVFORGE_BACKEND must be 'local' or 'aws', got: {mode!r}")


# Convenience re-export so callers can do `from backend.common import admin_headers`.
from ._http import admin_headers  # noqa: E402
