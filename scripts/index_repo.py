"""CLI: clone + AST-chunk + embed a tenant's repo into the vector store.

Usage:
    uv run python -m scripts.index_repo <tenant_id>

Reads .env / .env.local. Uses the control plane to mint a fresh installation token.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=False)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

    if len(sys.argv) != 2:
        sys.exit("usage: index_repo.py <tenant_id>")
    try:
        tenant_id = int(sys.argv[1])
    except ValueError:
        sys.exit("tenant_id must be an integer")

    api = os.environ.get("CONTROL_PLANE_API", "http://localhost:8001")

    print(f"[index] fetching tenant {tenant_id} from {api} ...", flush=True)
    t = httpx.get(f"{api}/tenants/{tenant_id}", timeout=15.0)
    t.raise_for_status()
    tenant = t.json()
    if not tenant.get("repos"):
        sys.exit(f"tenant {tenant_id} has no repos registered")
    repo_full_name = tenant["repos"][0]["full_name"]
    print(f"[index] repo: {repo_full_name}", flush=True)

    tok = httpx.get(f"{api}/tenants/{tenant_id}/installation-token", timeout=30.0)
    tok.raise_for_status()
    token = tok.json()["token"]
    print(f"[index] installation token minted, expires {tok.json()['expires_at']}", flush=True)

    # Import AFTER we know we have a token so .env is loaded before backend.common reads it.
    from backend.ingest.index_tenant_repo import index_repo

    stats = index_repo(tenant_id, repo_full_name, token)
    print()
    print("Done. Stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
