"""DevForge orchestrator — the full crew, end-to-end.

Runs: fetch_tenant -> mint_install_token -> scrub_ticket -> prepare_worktree
-> search_codebase -> Lead -> Backend+Frontend per step -> QA -> (commit + push
already done by Backend; QA opens the PR) -> persist events -> cleanup.

Streams JSON-line events to stdout for CLI consumption; persists every event
to the `job_events` table so a frontend can replay them later.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.common import get_backend
from backend.cost.tracker import CostCapExceeded, default_cap, end_job, start_job
from backend.ingest.index_tenant_repo import search_codebase
from backend.safety import (
    classify_plan_step,
    is_forbidden,
    list_pending,
    scrub,
    verify_and_consume,
)
from backend.worker.backend_engineer import commit_and_push, run_backend_step
from backend.worker.frontend_engineer import run_frontend_step
from backend.worker.lead import plan_ticket
from backend.worker.qa_engineer import run_qa
from backend.worker.schemas import StepKind, TaskPlan
from backend.worker.worktree import Worktree, prepare_worktree


# ------------- event emitter ---------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(job_id: int | None, event: str, payload: dict | None = None) -> None:
    """Write an event to stdout (JSON line) + persist to job_events."""
    rec = {"t": _now_iso(), "event": event, "payload": payload or {}}
    print(json.dumps(rec), flush=True)
    if job_id is not None:
        try:
            get_backend().db.execute(
                "INSERT INTO job_events (job_id, event, payload) VALUES (:j, :e, :p)",
                {"j": job_id, "e": event, "p": json.dumps(payload or {})},
            )
        except Exception as exc:
            # Never let observability crash the run.
            print(
                json.dumps({"t": _now_iso(), "event": "event_persist_failed",
                            "payload": {"error": str(exc)}}),
                flush=True,
            )


def _persist_job(tenant_id: int, repo_id: int, title: str, body: str) -> int:
    rows = get_backend().db.execute(
        """
        INSERT INTO jobs (tenant_id, repo_id, ticket_title, ticket_body, status)
        VALUES (:t, :r, :title, :body, 'running')
        RETURNING id
        """,
        {"t": tenant_id, "r": repo_id, "title": title, "body": body},
    )
    return rows[0]["id"]


def _update_job_status(job_id: int, status: str, pr_url: str | None = None) -> None:
    if pr_url is not None:
        get_backend().db.execute(
            "UPDATE jobs SET status=:s, pr_url=:u WHERE id=:j",
            {"s": status, "u": pr_url, "j": job_id},
        )
    else:
        get_backend().db.execute(
            "UPDATE jobs SET status=:s WHERE id=:j",
            {"s": status, "j": job_id},
        )


# ------------- main entrypoint -------------------------------------------

async def run_job(
    *,
    tenant_id: int,
    ticket_id: str,
    ticket_title: str,
    ticket_body: str,
    approval_token: str | None = None,
) -> dict:
    """Run the full crew for a ticket. Returns a summary dict at end."""
    api = os.environ.get("CONTROL_PLANE_API", "http://localhost:8001")

    _emit(None, "job_started", {
        "tenant_id": tenant_id, "ticket_id": ticket_id, "ticket_title": ticket_title,
    })

    # Scrub ticket body for prompt injection. Use scrubbed body for Lead.
    cleaned_body, injections = scrub(ticket_body)
    if injections:
        _emit(None, "injection_detected", {
            "where": "ticket_body", "count": len(injections), "patterns": injections[:5],
        })

    # Tenant lookup + installation token mint.
    t = httpx.get(f"{api}/tenants/{tenant_id}", timeout=15.0)
    t.raise_for_status()
    tenant = t.json()
    if not tenant.get("repos"):
        _emit(None, "error", {"reason": "no repos registered for tenant"})
        return {"ok": False, "reason": "no repos"}
    repo = tenant["repos"][0]
    repo_full_name = repo["full_name"]
    repo_id = repo["id"]
    _emit(None, "tenant_fetched", {"repo": repo_full_name})

    tok = httpx.get(f"{api}/tenants/{tenant_id}/installation-token", timeout=30.0)
    tok.raise_for_status()
    installation_token = tok.json()["token"]
    _emit(None, "token_minted", {"expires_at": tok.json()["expires_at"]})

    # Persist job row.
    job_id = _persist_job(tenant_id, repo_id, ticket_title, ticket_body)
    _emit(job_id, "job_persisted", {"job_id": job_id})

    # Start per-job cost tracking. Cap controlled by DEVFORGE_JOB_COST_CAP_USD.
    cap = default_cap()
    start_job(job_id=job_id, cap_usd=cap)
    _emit(job_id, "cost_tracking_started", {"cap_usd": cap})

    # RAG retrieval over tenant's codebase. The content retrieved is ALSO scrubbed
    # before the Lead sees it — repo READMEs are attacker-controlled content.
    hits = search_codebase(tenant_id, f"{ticket_title}\n{cleaned_body}", k=6)
    for h in hits:
        meta = h.get("metadata") or {}
        text = h.get("text") or meta.get("text") or ""
        cleaned, injections = scrub(text)
        if injections:
            _emit(job_id, "injection_detected", {
                "where": f"rag:{meta.get('file')}:{meta.get('start_line')}",
                "count": len(injections),
                "patterns": injections[:5],
            })
        # Replace the text in the hit so Lead sees the scrubbed version.
        h["text"] = cleaned
        if "metadata" in h:
            h["metadata"]["text"] = cleaned
    _emit(job_id, "rag_hits", {"count": len(hits)})

    # Lead agent.
    plan: TaskPlan = await plan_ticket(ticket_id, ticket_title, cleaned_body, hits)
    _emit(job_id, "lead_planned", {
        "steps": [{"id": s.id, "kind": s.kind.value, "desc": s.description[:140]} for s in plan.steps],
        "requires_human_approval": plan.requires_human_approval,
        "estimated_cost_usd": plan.estimated_cost_usd,
    })

    # SafetyGuard: if any step is catastrophic, bail immediately.
    for s in plan.steps:
        sev = classify_plan_step(s.description, s.files_likely_touched)
        if sev == "catastrophic":
            _emit(job_id, "safety_refused", {"step": s.id, "reason": "catastrophic classification"})
            _update_job_status(job_id, "refused")
            return {"ok": False, "job_id": job_id, "reason": "catastrophic step"}

    # SafetyGuard: if the plan requires human approval, check for an approval token.
    if plan.requires_human_approval:
        # The command we're approving is the job itself (title + body digest).
        approval_command = f"run_job:{tenant_id}:{ticket_id}:{ticket_title}"
        if not approval_token or not verify_and_consume(
            job_id=job_id, command=approval_command, token_raw=approval_token,
        ):
            _emit(job_id, "approval_required", {
                "reason": "plan has migration/dependency/infra step",
                "hint": (
                    f"Mint a token then re-run with DEVFORGE_APPROVAL_TOKEN set.\n"
                    f"  python -m scripts.mint_approval {job_id} '{approval_command}'"
                ),
            })
            _update_job_status(job_id, "awaiting_approval")
            return {"ok": False, "job_id": job_id, "reason": "approval required"}
        _emit(job_id, "approval_consumed", {"job_id": job_id})

    # Worktree.
    wt: Worktree = prepare_worktree(tenant_id, repo_full_name, installation_token)
    _emit(job_id, "worktree_ready", {"branch": wt.branch})

    try:
        # Run each step through its owning agent.
        for step in plan.steps:
            _emit(job_id, "step_started", {"id": step.id, "kind": step.kind.value})
            if step.kind == StepKind.BACKEND:
                result = await run_backend_step(tenant_id, step, wt.worktree_path)
            elif step.kind == StepKind.FRONTEND:
                result = await run_frontend_step(tenant_id, step, wt.worktree_path)
            elif step.kind == StepKind.MIGRATION:
                _emit(job_id, "migration_skipped", {"id": step.id,
                      "note": "migration steps are human-run; see DEMO.md"})
                continue
            else:  # QA step in the plan — the real QA gates run at the end below.
                continue
            _emit(job_id, "step_finished", {
                "id": step.id, "success": result.success,
                "summary": result.summary, "files": result.files_changed,
            })
            if not result.success:
                _update_job_status(job_id, "failed")
                _emit(job_id, "job_done", {"ok": False, "reason": "step failed"})
                return {"ok": False, "job_id": job_id}

        # Commit what the engineers produced, push the branch.
        push = commit_and_push(wt.worktree_path, wt.branch, wt.remote_url,
                               commit_message=f"{ticket_id}: {ticket_title}\n\n{plan.analysis}")
        _emit(job_id, "branch_pushed", push)
        if not push.get("pushed"):
            _update_job_status(job_id, "failed")
            _emit(job_id, "job_done", {"ok": False, "reason": "nothing to push"})
            return {"ok": False, "job_id": job_id}

        # QA gates + PR open.
        _emit(job_id, "qa_started", {})
        qa = await run_qa(
            tenant_id=tenant_id,
            repo_full_name=repo_full_name,
            branch=wt.branch,
            installation_token=installation_token,
            ticket_title=ticket_title,
            ticket_body=ticket_body,
            worktree=wt.worktree_path,
        )
        if qa.passed:
            _emit(job_id, "qa_gate_passed", {"findings": len(qa.findings)})
            if qa.pr_url:
                _emit(job_id, "pr_opened", {"url": qa.pr_url})
                _update_job_status(job_id, "pr_opened", qa.pr_url)
                _emit(job_id, "job_done", {"ok": True, "pr_url": qa.pr_url})
                return {"ok": True, "job_id": job_id, "pr_url": qa.pr_url}
            _emit(job_id, "pr_open_failed", {})
            _update_job_status(job_id, "failed")
            return {"ok": False, "job_id": job_id}
        else:
            _emit(job_id, "qa_gate_failed", {
                "findings": [f.model_dump() for f in qa.findings][:10],
                "count": len(qa.findings),
            })
            _update_job_status(job_id, "failed")
            _emit(job_id, "job_done", {"ok": False, "reason": "qa gates failed"})
            return {"ok": False, "job_id": job_id}
    finally:
        wt.cleanup()
        # Always emit a cost summary so the dashboard has data, even on failure.
        state = end_job()
        if state is not None:
            _emit(job_id, "cost_summary", {
                "spent_usd": round(state.spent_usd, 6),
                "cap_usd": state.cap_usd,
                "calls": state.calls,
                "by_model": {k: round(v, 6) for k, v in state.by_model.items()},
            })
