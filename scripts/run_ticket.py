"""End-to-end: ticket -> Lead plan -> BackendEngineer -> commit + push branch.

Usage:
    uv run python -m scripts.run_ticket <tenant_id>

Reads DEVFORGE_TICKET_TITLE + DEVFORGE_TICKET_BODY from env (with sensible
defaults for the demo).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
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

    # Control plane: fetch tenant + mint installation token.
    api = os.environ.get("CONTROL_PLANE_API", "http://localhost:8001")
    t = httpx.get(f"{api}/tenants/{tenant_id}", timeout=15.0)
    t.raise_for_status()
    tenant = t.json()
    repo_full_name = tenant["repos"][0]["full_name"]
    tok = httpx.get(f"{api}/tenants/{tenant_id}/installation-token", timeout=30.0)
    tok.raise_for_status()
    token = tok.json()["token"]

    # Planning
    from backend.ingest.index_tenant_repo import search_codebase
    from backend.worker.lead import plan_ticket
    from backend.worker.schemas import StepKind
    from backend.worker.worktree import prepare_worktree
    from backend.worker.backend_engineer import run_backend_step, commit_and_push

    print(f"=== ticket: {ticket_id} — {ticket_title} ===")
    print(f"=== repo:   {repo_full_name} ===\n")

    print("[1/4] retrieving codebase context ...", flush=True)
    hits = search_codebase(tenant_id, f"{ticket_title}\n{ticket_body}", k=6)

    print("[2/4] asking EngineeringLead for a TaskPlan ...", flush=True)
    plan = await plan_ticket(ticket_id, ticket_title, ticket_body, hits)
    print(f"    steps:")
    for s in plan.steps:
        print(f"      #{s.id} [{s.kind.value}] {s.description[:90]}")
    print(f"    requires_human_approval: {plan.requires_human_approval}")

    backend_steps = [s for s in plan.steps if s.kind == StepKind.BACKEND]
    if not backend_steps:
        print("no backend steps in plan — nothing for BackendEngineer to do.")
        return

    print(f"\n[3/4] preparing worktree ...", flush=True)
    wt = prepare_worktree(tenant_id, repo_full_name, token)
    print(f"    worktree: {wt.worktree_path}")
    print(f"    branch:   {wt.branch}")

    try:
        for step in backend_steps:
            print(f"\n[3/4] running BackendEngineer on step #{step.id} ...", flush=True)
            result = await run_backend_step(tenant_id, step, wt.worktree_path)
            print(f"    success: {result.success}")
            print(f"    summary: {result.summary}")
            print(f"    files:   {result.files_changed}")
            print(f"    tests:   {result.test_result}")
            if not result.success:
                print("stopping: step did not pass tests.")
                return

        commit_message = f"{ticket_id}: {ticket_title}\n\n{plan.analysis}"
        print(f"\n[4/4] committing + pushing branch {wt.branch} ...", flush=True)
        push = commit_and_push(wt.worktree_path, wt.branch, wt.remote_url, commit_message)
        print(f"    {push}")
        if push.get("pushed"):
            print(f"\nDone. Branch live at:")
            print(f"  https://github.com/{repo_full_name}/tree/{wt.branch}")
            print(f"Open a PR with:")
            print(f"  gh pr create --repo {repo_full_name} --base main --head {wt.branch} "
                  f"--title \"{ticket_id}: {ticket_title}\"")
    finally:
        wt.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
