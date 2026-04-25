"""HTTP helper for CLI scripts + the orchestrator.

Centralises the `X-Admin-Token` header so every script that calls the
control plane uses the same wiring. The header is sent unconditionally
when `DEVFORGE_ADMIN_TOKEN` is set, even if the control plane is in
auth-disabled mode — extra headers are harmless on a permissive server.
"""
from __future__ import annotations

import os
from typing import Mapping


def admin_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return headers including X-Admin-Token if DEVFORGE_ADMIN_TOKEN is set.

    Use as:

        import httpx
        from backend.common._http import admin_headers

        r = httpx.get(f"{api}/tenants/1", headers=admin_headers(), timeout=15.0)
    """
    headers: dict[str, str] = {}
    token = os.environ.get("DEVFORGE_ADMIN_TOKEN")
    if token:
        headers["X-Admin-Token"] = token
    if extra:
        headers.update(extra)
    return headers
