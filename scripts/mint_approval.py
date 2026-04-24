"""Mint an approval token for a destructive-ops job.

Two modes:

  Local mint (calls backend.safety.mint directly — needs SQLite/Aurora access):
      uv run python -m scripts.mint_approval <job_id> "<command>"

  HTTP mint via control plane (uses DEVFORGE_ADMIN_TOKEN env var):
      uv run python -m scripts.mint_approval <job_id> "<command>" --http

The HTTP path is what a real human-approver UX would use, since it goes
through the same admin-token-gated endpoint a future Clerk-protected web UI
would call. The local path is useful for tests + dev scripts that already
have direct DB access.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)


def main() -> None:
    args = sys.argv[1:]
    use_http = "--http" in args
    args = [a for a in args if a != "--http"]
    if len(args) != 2:
        sys.exit('usage: mint_approval.py <job_id> "<command>" [--http]')
    job_id = int(args[0])
    command = args[1]

    if use_http:
        api = os.environ.get("CONTROL_PLANE_API", "http://localhost:8001")
        admin = os.environ.get("DEVFORGE_ADMIN_TOKEN")
        if not admin:
            sys.exit("DEVFORGE_ADMIN_TOKEN not set in env")
        r = httpx.post(
            f"{api}/jobs/{job_id}/approve",
            headers={"X-Admin-Token": admin, "Content-Type": "application/json"},
            json={"command": command},
            timeout=15.0,
        )
        if r.status_code != 200:
            sys.exit(f"mint failed: {r.status_code} {r.text}")
        print(f"DEVFORGE_APPROVAL_TOKEN={r.json()['token']}")
        return

    from backend.safety import mint
    token = mint(job_id=job_id, command=command)
    print(f"DEVFORGE_APPROVAL_TOKEN={token}")


if __name__ == "__main__":
    main()
