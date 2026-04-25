"""Mint an approval token for a destructive-ops ticket or job.

Two flavors:

  Ticket-bound (RECOMMENDED for migration / dep-bump approvals):
      uv run python -m scripts.mint_approval --ticket "<command>" --http
      uv run python -m scripts.mint_approval --ticket "<command>"   # local

  Job-bound (legacy — only useful for tests + redteam strict-scope):
      uv run python -m scripts.mint_approval <job_id> "<command>" [--http]

The ticket-bound form is correct for human approval flows. Every
run_ticket call creates a fresh jobs.id — a token bound to job_id=N can
only authorize the run that just failed and isn't rerunable. A
ticket-bound token authorizes any run for the same `command` string
(typically `run_job:<tenant_id>:<ticket_id>:<title>`).

HTTP mode goes through the admin-token-gated control-plane endpoint —
the path a Clerk-protected web UI would use.
Local mode talks to the DB directly.
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


def _http_mint(*, command: str, job_id: int | None) -> str:
    api = os.environ.get("CONTROL_PLANE_API", "http://localhost:8001")
    admin = os.environ.get("DEVFORGE_ADMIN_TOKEN")
    if not admin:
        sys.exit("DEVFORGE_ADMIN_TOKEN not set in env")
    url = f"{api}/jobs/{job_id}/approve" if job_id is not None else f"{api}/approvals"
    r = httpx.post(
        url,
        headers={"X-Admin-Token": admin, "Content-Type": "application/json"},
        json={"command": command},
        timeout=15.0,
    )
    if r.status_code != 200:
        sys.exit(f"mint failed: {r.status_code} {r.text}")
    return r.json()["token"]


def _local_mint(*, command: str, job_id: int | None) -> str:
    from backend.safety import mint
    return mint(command=command, job_id=job_id)


def main() -> None:
    args = sys.argv[1:]
    use_http = "--http" in args
    args = [a for a in args if a != "--http"]

    job_id: int | None = None
    command: str | None = None

    if "--ticket" in args:
        idx = args.index("--ticket")
        if idx + 1 >= len(args):
            sys.exit('--ticket needs a value (the approval_command from the orchestrator)')
        command = args[idx + 1]
    elif len(args) == 2:
        # legacy form: <job_id> <command>
        try:
            job_id = int(args[0])
        except ValueError:
            sys.exit('first positional arg must be job_id (or use --ticket "<command>")')
        command = args[1]
    else:
        sys.exit(
            'usage:\n'
            '  mint_approval.py --ticket "<command>" [--http]\n'
            '  mint_approval.py <job_id> "<command>" [--http]'
        )

    token = _http_mint(command=command, job_id=job_id) if use_http \
            else _local_mint(command=command, job_id=job_id)
    print(f"DEVFORGE_APPROVAL_TOKEN={token}")


if __name__ == "__main__":
    main()
