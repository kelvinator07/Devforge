"""DevForge control plane — FastAPI.

Runs locally (uvicorn) or on AWS Lambda (via Mangum). Backend chosen by
DEVFORGE_BACKEND=local|aws.

Day 3 surface:
  - GET  /health
  - POST /tenants/onboard
  - GET  /tenants/{tenant_id}
  - GET  /tenants/{tenant_id}/installation-token

Tier-2 additions:
  - GET  /jobs/{job_id}                   — job state + last 200 events
  - GET  /jobs/{job_id}/sse               — Server-Sent Events stream of job events
  - POST /jobs/{job_id}/approve           — admin-token-gated approval mint
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from mangum import Mangum
from pydantic import BaseModel, Field

# Local dev: load .env before anything else reads env.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)

from backend.common import get_backend  # noqa: E402
from backend.control_plane.github_app import installation_token_for  # noqa: E402


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("devforge-cp")

app = FastAPI(title="DevForge Control Plane", version="0.1.0")
_backend = get_backend()


class OnboardRequest(BaseModel):
    tenant_name: str = Field(..., min_length=1, max_length=128)
    github_owner: str = Field(..., min_length=1, max_length=128)
    repo_full_name: str = Field(..., pattern=r"^[^/]+/[^/]+$")
    default_branch: str = "main"
    installation_id: int


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "backend": os.environ.get("DEVFORGE_BACKEND", "local"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/tenants/onboard")
def onboard_tenant(req: OnboardRequest):
    existing = _backend.db.execute(
        "SELECT id FROM tenants WHERE github_installation_id = :inst",
        {"inst": req.installation_id},
    )
    if existing:
        tenant_id = existing[0]["id"]
        logger.info("tenant exists for installation_id=%s -> %s", req.installation_id, tenant_id)
    else:
        rows = _backend.db.execute(
            """
            INSERT INTO tenants (name, github_owner, github_installation_id)
            VALUES (:name, :owner, :inst)
            RETURNING id
            """,
            {"name": req.tenant_name, "owner": req.github_owner, "inst": req.installation_id},
        )
        tenant_id = rows[0]["id"]
        logger.info("created tenant %s for %s", tenant_id, req.tenant_name)

    existing_repo = _backend.db.execute(
        "SELECT id FROM repos WHERE tenant_id = :t AND full_name = :fn",
        {"t": tenant_id, "fn": req.repo_full_name},
    )
    if not existing_repo:
        _backend.db.execute(
            "INSERT INTO repos (tenant_id, full_name, default_branch) VALUES (:t, :fn, :db)",
            {"t": tenant_id, "fn": req.repo_full_name, "db": req.default_branch},
        )

    return {"tenant_id": tenant_id, "repo_full_name": req.repo_full_name}


@app.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: int):
    rows = _backend.db.execute(
        """
        SELECT t.id, t.name, t.github_owner, t.github_installation_id, t.created_at,
               r.id AS repo_id, r.full_name AS repo_full_name, r.default_branch
        FROM tenants t
        LEFT JOIN repos r ON r.tenant_id = t.id
        WHERE t.id = :tid
        """,
        {"tid": tenant_id},
    )
    if not rows:
        raise HTTPException(404, "tenant not found")
    return {
        "id": rows[0]["id"],
        "name": rows[0]["name"],
        "github_owner": rows[0]["github_owner"],
        "github_installation_id": rows[0]["github_installation_id"],
        "created_at": rows[0]["created_at"],
        "repos": [
            {"id": r["repo_id"], "full_name": r["repo_full_name"], "default_branch": r["default_branch"]}
            for r in rows if r.get("repo_id") is not None
        ],
    }


# ============================================================================
# Job state + SSE event stream
# ============================================================================

@app.get("/jobs/{job_id}")
def get_job(job_id: int, since_event_id: int = 0, limit: int = 200):
    """Snapshot of a job + its events (oldest first, capped at `limit`)."""
    rows = _backend.db.execute(
        "SELECT id, tenant_id, ticket_title, status, pr_url, created_at FROM jobs WHERE id=:j",
        {"j": job_id},
    )
    if not rows:
        raise HTTPException(404, "job not found")
    job = rows[0]
    events = _backend.db.execute(
        """
        SELECT id, event, payload, ts
        FROM job_events
        WHERE job_id=:j AND id > :since
        ORDER BY id
        LIMIT :lim
        """,
        {"j": job_id, "since": since_event_id, "lim": limit},
    )
    return {"job": job, "events": events}


@app.get("/jobs/{job_id}/sse")
async def job_sse(job_id: int):
    """Stream job events as SSE.

    Polls the events table every second. Closes when the job reaches a
    terminal state (pr_opened | failed | refused | awaiting_approval).
    """
    if not _backend.db.execute("SELECT id FROM jobs WHERE id=:j", {"j": job_id}):
        raise HTTPException(404, "job not found")

    TERMINAL = {"pr_opened", "failed", "refused", "awaiting_approval"}

    async def stream():
        last_id = 0
        idle_ticks = 0
        while True:
            rows = _backend.db.execute(
                """
                SELECT id, event, payload, ts
                FROM job_events
                WHERE job_id=:j AND id > :last
                ORDER BY id
                """,
                {"j": job_id, "last": last_id},
            )
            for r in rows:
                last_id = r["id"]
                idle_ticks = 0
                # SSE frame: id + event + data lines, blank-line terminator.
                payload_str = r["payload"] or "{}"
                yield (
                    f"id: {r['id']}\n"
                    f"event: {r['event']}\n"
                    f"data: {payload_str}\n\n"
                )

            # Check terminal status.
            srows = _backend.db.execute("SELECT status FROM jobs WHERE id=:j", {"j": job_id})
            status = (srows[0]["status"] if srows else None) or ""
            if status in TERMINAL:
                # Emit a final close frame and break.
                yield f"event: stream_closed\ndata: {json.dumps({'status': status})}\n\n"
                break

            # Heartbeat every 15 idle seconds so proxies don't time out.
            idle_ticks += 1
            if idle_ticks % 15 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# Approval mint (admin-only)
# ============================================================================

class ApproveRequest(BaseModel):
    command: str = Field(..., description="Command-string the token authorizes (orchestrator format).")


@app.post("/jobs/{job_id}/approve")
def approve_job(
    job_id: int,
    req: ApproveRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Mint a one-time, command-bound, 5-minute approval token for `job_id`.

    Gated by `X-Admin-Token` header which must match `DEVFORGE_ADMIN_TOKEN` env.
    Bypasses the agent tool surface entirely — agents never see this endpoint.
    """
    expected = os.environ.get("DEVFORGE_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(503, "DEVFORGE_ADMIN_TOKEN not configured on control plane")
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(403, "invalid admin token")
    if not _backend.db.execute("SELECT id FROM jobs WHERE id=:j", {"j": job_id}):
        raise HTTPException(404, "job not found")

    from backend.safety import mint
    token = mint(job_id=job_id, command=req.command)
    return {"token": token, "job_id": job_id, "command": req.command}


# ============================================================================
# Existing endpoints
# ============================================================================

@app.get("/tenants/{tenant_id}/installation-token")
def get_installation_token(tenant_id: int):
    rows = _backend.db.execute(
        "SELECT github_installation_id FROM tenants WHERE id = :tid",
        {"tid": tenant_id},
    )
    if not rows:
        raise HTTPException(404, "tenant not found")
    installation_id = rows[0]["github_installation_id"]
    app_id = os.environ.get("GITHUB_APP_ID")
    if not app_id:
        raise HTTPException(500, "GITHUB_APP_ID not set")
    try:
        token, expires_at = installation_token_for(app_id, installation_id)
    except Exception as exc:
        logger.error("installation_token mint failed: %s", exc, exc_info=True)
        raise HTTPException(502, "failed to mint installation token") from exc
    return {"token": token, "expires_at": expires_at}


# Lambda entrypoint (used by the aws image; local dev uses uvicorn directly).
handler = Mangum(app, lifespan="off")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("DEVFORGE_CP_PORT", "8001"))
    uvicorn.run("backend.control_plane.main:app", host="0.0.0.0", port=port, reload=True)
