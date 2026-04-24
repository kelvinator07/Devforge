"""Run a ticket through the full DevForge crew.

Usage:
    uv run python -m scripts.run_ticket <tenant_id>

Environment:
    DEVFORGE_TICKET_ID       (default: DEMO-1)
    DEVFORGE_TICKET_TITLE
    DEVFORGE_TICKET_BODY
    DEVFORGE_APPROVAL_TOKEN  (required when the plan asks for approval)

Streams JSON-lines events on stdout. Pipe to `jq .` for pretty output.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)


async def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: run_ticket.py <tenant_id>")
    tenant_id = int(sys.argv[1])

    ticket_id = os.environ.get("DEVFORGE_TICKET_ID", "DEMO-1")
    ticket_title = os.environ.get(
        "DEVFORGE_TICKET_TITLE",
        "Add /stats endpoint returning user count",
    )
    ticket_body = os.environ.get(
        "DEVFORGE_TICKET_BODY",
        "Add a GET /stats endpoint to app/main.py that returns "
        '{"user_count": N} where N is len(USERS). Add a test in '
        "tests/test_main.py asserting status 200 and the correct count.",
    )
    approval_token = os.environ.get("DEVFORGE_APPROVAL_TOKEN")

    from backend.worker.orchestrator import run_job
    result = await run_job(
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        ticket_title=ticket_title,
        ticket_body=ticket_body,
        approval_token=approval_token,
    )
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
