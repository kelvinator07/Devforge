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
  - POST /jobs/{job_id}/approve           — admin-token-gated approval mint (job-bound)
  - POST /approvals                       — admin-token-gated approval mint (command-bound)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
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


# ============================================================================
# Dual auth: Clerk JWT (frontend) OR X-Admin-Token (CLI) OR DEVFORGE_AUTH_DISABLED.
# /health is open. /approvals + /jobs/{id}/approve stay admin-token-only.
# ============================================================================

_clerk_jwks_url = os.environ.get("CLERK_JWKS_URL", "").strip()
_clerk_guard = None
if _clerk_jwks_url:
    try:
        from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer  # type: ignore
        _clerk_guard = ClerkHTTPBearer(ClerkConfig(jwks_url=_clerk_jwks_url))
        logger.info("Clerk JWT validation enabled via %s", _clerk_jwks_url)
    except Exception as exc:  # pragma: no cover - never break the app on bad clerk wiring
        logger.warning("Clerk JWT init failed (%s); continuing without it", exc)


def _auth_disabled_local() -> bool:
    """`DEVFORGE_AUTH_DISABLED=1` lets local CLI dev bypass auth entirely.

    Refuses to engage when DEVFORGE_BACKEND=aws — escape hatch must never
    open up production.
    """
    if os.environ.get("DEVFORGE_BACKEND", "local") != "local":
        return False
    return os.environ.get("DEVFORGE_AUTH_DISABLED", "").strip() in ("1", "true", "yes")


def _admin_token_matches(token: str | None) -> bool:
    expected = os.environ.get("DEVFORGE_ADMIN_TOKEN")
    return bool(expected and token and token == expected)


def _check_admin(token: str | None) -> None:
    """Strict admin-only check. Used by /approvals and /jobs/{id}/approve."""
    expected = os.environ.get("DEVFORGE_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(503, "DEVFORGE_ADMIN_TOKEN not configured on control plane")
    if not _admin_token_matches(token):
        raise HTTPException(403, "invalid admin token")


def _authorize_tenant_admin(auth: dict, tenant_id: int) -> None:
    """Caller must be either (a) admin via X-Admin-Token, (b) anonymous via the
    DEVFORGE_AUTH_DISABLED local escape hatch, or (c) a Clerk user whose
    user_id/org_id maps to this tenant. Used by browser-facing admin
    operations (#B2) so the frontend never needs to ship an admin secret.
    """
    actor = auth.get("actor")
    if actor in ("admin", "anonymous"):
        return
    if actor != "user":
        raise HTTPException(401, "admin operation requires Clerk session or admin token")
    rows = _backend.db.execute(
        "SELECT clerk_user_id, clerk_org_id FROM tenants WHERE id = :t",
        {"t": tenant_id},
    )
    if not rows:
        raise HTTPException(404, "tenant not found")
    t = rows[0]
    if t["clerk_org_id"] and t["clerk_org_id"] == auth.get("org_id"):
        return
    if t["clerk_user_id"] and t["clerk_user_id"] == auth.get("sub"):
        return
    raise HTTPException(403, "you are not a member of this tenant")


def dual_auth(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Allow Clerk JWT OR admin token OR auth-disabled local dev.

    Returns a dict describing who the caller is (for logging only — we
    don't enforce per-tenant scoping in v1).
    """
    if _admin_token_matches(x_admin_token):
        return {"actor": "admin", "via": "X-Admin-Token"}

    if _auth_disabled_local():
        return {"actor": "anonymous", "via": "DEVFORGE_AUTH_DISABLED"}

    if authorization and authorization.lower().startswith("bearer "):
        if _clerk_guard is None:
            raise HTTPException(
                503,
                "Clerk JWT validation not configured (set CLERK_JWKS_URL or "
                "DEVFORGE_AUTH_DISABLED=1 for local dev)",
            )
        token = authorization.split(" ", 1)[1].strip()
        try:
            # fastapi-clerk-auth >=0.0.7 keeps the JWT decoder as a private
            # method (`_decode_token`). The public `__call__` only works
            # when called as a FastAPI Depends with a real Request, which
            # we don't have here. Calling _decode_token directly is the
            # supported escape hatch (returns dict on success, None on
            # any verification failure when debug_mode=False).
            decoded = _clerk_guard._decode_token(token)  # noqa: SLF001
        except Exception as exc:
            raise HTTPException(401, f"Clerk JWT decode error: {exc}") from exc
        if decoded is None:
            raise HTTPException(
                401,
                "invalid Clerk JWT (signature/audience/issuer/expiry failed). "
                "Confirm CLERK_JWKS_URL points at YOUR Clerk app, not the "
                ".env.example placeholder.",
            )
        return {
            "actor": "user",
            "via": "clerk",
            "sub": decoded.get("sub"),
            # Clerk Organizations claims (None when Orgs aren't enabled or the
            # user is signed into a personal workspace). #B1 uses these to
            # resolve the caller's tenant via /tenants/me.
            "org_id": decoded.get("org_id"),
            "org_role": decoded.get("org_role"),
        }

    raise HTTPException(
        401,
        "missing credentials: send X-Admin-Token or Authorization: Bearer <clerk-jwt>, "
        "or set DEVFORGE_AUTH_DISABLED=1 for local dev",
    )


# ============================================================================
# CORS: allow the local frontend dev origin + a configurable production origin.
# ============================================================================

_allowed_origins = [o.strip() for o in os.environ.get(
    "DEVFORGE_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)


class OnboardRequest(BaseModel):
    tenant_name: str = Field(..., min_length=1, max_length=128)
    github_owner: str = Field(..., min_length=1, max_length=128)
    repo_full_name: str = Field(..., pattern=r"^[^/]+/[^/]+$")
    default_branch: str = "main"
    installation_id: int
    # B1: optional Clerk identity binding so /tenants/me resolves the tenant
    # from a signed-in user's JWT. Both nullable for backward compat.
    clerk_user_id: str | None = None
    clerk_org_id: str | None = None


class SubmitJobRequest(BaseModel):
    tenant_id: int
    ticket_title: str = Field(..., min_length=1, max_length=512)
    ticket_body: str = Field(..., min_length=1, max_length=8192)
    ticket_id: str = "DEMO-1"
    approval_token: str | None = None


class ApproveAndRunRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=512)
    tenant_id: int
    ticket_title: str = Field(..., min_length=1, max_length=512)
    ticket_body: str = Field(..., min_length=1, max_length=8192)
    ticket_id: str = "DEMO-1"


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "backend": os.environ.get("DEVFORGE_BACKEND", "local"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/tenants/onboard")
def onboard_tenant(req: OnboardRequest, _auth: dict = Depends(dual_auth)):
    existing = _backend.db.execute(
        "SELECT id FROM tenants WHERE github_installation_id = :inst",
        {"inst": req.installation_id},
    )
    if existing:
        tenant_id = existing[0]["id"]
        logger.info("tenant exists for installation_id=%s -> %s", req.installation_id, tenant_id)
        # Idempotently update Clerk identity if the caller provided one and
        # the row didn't have one yet — useful for backfill via re-onboard.
        if req.clerk_user_id or req.clerk_org_id:
            _backend.db.execute(
                """
                UPDATE tenants
                SET clerk_user_id = COALESCE(clerk_user_id, :u),
                    clerk_org_id  = COALESCE(clerk_org_id,  :o)
                WHERE id = :t
                """,
                {"u": req.clerk_user_id, "o": req.clerk_org_id, "t": tenant_id},
            )
    else:
        rows = _backend.db.execute(
            """
            INSERT INTO tenants (name, github_owner, github_installation_id,
                                 clerk_user_id, clerk_org_id)
            VALUES (:name, :owner, :inst, :u, :o)
            RETURNING id
            """,
            {"name": req.tenant_name, "owner": req.github_owner,
             "inst": req.installation_id,
             "u": req.clerk_user_id, "o": req.clerk_org_id},
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


def _fetch_tenant(tenant_id: int) -> dict:
    """Shared loader for tenant + repos. Raises 404 if missing."""
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


@app.get("/tenants/me")
def get_current_tenant(_auth: dict = Depends(dual_auth)):
    """Resolve the requester's tenant from their Clerk JWT. Prefers org-scoped
    binding (clerk_org_id) and falls back to user-scoped (clerk_user_id) for
    solo accounts where Clerk Organizations aren't enabled."""
    if _auth.get("actor") != "user":
        raise HTTPException(403, "GET /tenants/me requires a Clerk session")
    org_id = _auth.get("org_id")
    user_id = _auth.get("sub")
    rows: list = []
    if org_id:
        rows = _backend.db.execute(
            "SELECT id FROM tenants WHERE clerk_org_id = :o", {"o": org_id})
    if not rows and user_id:
        rows = _backend.db.execute(
            "SELECT id FROM tenants WHERE clerk_user_id = :u", {"u": user_id})
    if not rows:
        raise HTTPException(
            404,
            "no tenant configured for this Clerk identity. "
            "Run scripts/link_tenant_clerk_identity.py to backfill.",
        )
    return _fetch_tenant(rows[0]["id"])


@app.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: int, _auth: dict = Depends(dual_auth)):
    return _fetch_tenant(tenant_id)


# ============================================================================
# Job state + SSE event stream
# ============================================================================

@app.get("/jobs/{job_id}")
def get_job(job_id: int, since_event_id: int = 0, limit: int = 200,
            _auth: dict = Depends(dual_auth)):
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


# `_check_admin` is defined near the dual_auth helper above. Keep this section
# focused on the approval mint endpoints + the new list endpoints.


@app.get("/jobs")
def list_jobs(tenant_id: int | None = None, limit: int = 50,
              _auth: dict = Depends(dual_auth)):
    """List recent jobs (newest first). Optional ?tenant_id= filter."""
    limit = max(1, min(limit, 200))
    if tenant_id is None:
        rows = _backend.db.execute(
            """
            SELECT id, tenant_id, ticket_title, status, pr_url, created_at
            FROM jobs
            ORDER BY id DESC
            LIMIT :lim
            """,
            {"lim": limit},
        )
    else:
        rows = _backend.db.execute(
            """
            SELECT id, tenant_id, ticket_title, status, pr_url, created_at
            FROM jobs
            WHERE tenant_id = :t
            ORDER BY id DESC
            LIMIT :lim
            """,
            {"t": tenant_id, "lim": limit},
        )
    return {"jobs": rows}


_ECS_CLIENT = None  # lazy-init: only constructed in AWS mode


def _dispatch_subprocess(
    *, job_id: int, tenant_id: int, ticket_id: str,
    ticket_title: str, ticket_body: str, approval_token: str | None,
) -> str:
    """Spawn `scripts.run_ticket` as a detached subprocess. Returns log path."""
    import subprocess
    env = dict(os.environ)
    env["DEVFORGE_TICKET_ID"] = ticket_id
    env["DEVFORGE_TICKET_TITLE"] = ticket_title
    env["DEVFORGE_TICKET_BODY"] = ticket_body
    env["DEVFORGE_JOB_ID"] = str(job_id)
    if approval_token:
        env["DEVFORGE_APPROVAL_TOKEN"] = approval_token

    log_dir = _REPO_ROOT / "data" / "job_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"job_{job_id}.log"
    log_fp = log_path.open("a")
    subprocess.Popen(
        ["uv", "run", "python", "-m", "scripts.run_ticket", str(tenant_id)],
        cwd=str(_REPO_ROOT),
        env=env,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return str(log_path)


def _dispatch_ecs_run_task(
    *, job_id: int, tenant_id: int, ticket_id: str,
    ticket_title: str, ticket_body: str, approval_token: str | None,
    control_plane_url: str,
) -> str:
    """Fire one Fargate task per ticket via ecs.run_task() with containerOverrides
    that mirror the env-var contract scripts/run_ticket.py reads. Returns a
    pseudo-log-path so callers can stay generic across local/AWS modes.
    """
    global _ECS_CLIENT
    if _ECS_CLIENT is None:
        import boto3
        _ECS_CLIENT = boto3.client("ecs")

    cluster  = os.environ["ECS_CLUSTER"]
    task_def = os.environ["ECS_TASK_DEFINITION"]
    subnets  = [s for s in os.environ["ECS_SUBNETS"].split(",") if s]
    sg       = os.environ["ECS_SECURITY_GROUP"]

    env_overrides = [
        {"name": "DEVFORGE_TICKET_ID",    "value": ticket_id},
        {"name": "DEVFORGE_TICKET_TITLE", "value": ticket_title},
        {"name": "DEVFORGE_TICKET_BODY",  "value": ticket_body},
        {"name": "DEVFORGE_JOB_ID",       "value": str(job_id)},
        {"name": "CONTROL_PLANE_API",     "value": control_plane_url},
    ]
    if approval_token:
        env_overrides.append(
            {"name": "DEVFORGE_APPROVAL_TOKEN", "value": approval_token}
        )

    resp = _ECS_CLIENT.run_task(
        cluster=cluster,
        taskDefinition=task_def,
        launchType="FARGATE",
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                "securityGroups": [sg],
                "assignPublicIp": "ENABLED",
            },
        },
        overrides={
            "containerOverrides": [{
                "name": "worker",
                # `uv run` is required so the script picks up the venv at
                # /app/.venv (where pyproject deps like dotenv live). Bare
                # `python` resolves to the system interpreter without those.
                "command": ["uv", "run", "python", "-m", "scripts.run_ticket", str(tenant_id)],
                "environment": env_overrides,
            }],
        },
    )
    failures = resp.get("failures") or []
    if failures:
        raise HTTPException(
            502,
            f"ecs.run_task failed: {failures[0].get('reason', 'unknown')}",
        )
    tasks = resp.get("tasks") or []
    task_arn = tasks[0]["taskArn"] if tasks else "<unknown>"
    return f"ecs:{task_arn}"


def _spawn_run_ticket(
    *, tenant_id: int, ticket_id: str, ticket_title: str, ticket_body: str,
    approval_token: str | None = None,
    control_plane_url: str | None = None,
) -> tuple[int, str]:
    """Validate tenant+repo, pre-create the queued jobs row, then dispatch:
    - DEVFORGE_BACKEND=aws  → ecs.run_task() spawns a fresh Fargate task
    - otherwise (local)     → subprocess.Popen scripts.run_ticket

    Returns (job_id, dispatch_handle). The handle is a log path locally,
    or "ecs:<task_arn>" on AWS — opaque to callers.
    """
    tenant_rows = _backend.db.execute(
        "SELECT id FROM tenants WHERE id = :t", {"t": tenant_id}
    )
    if not tenant_rows:
        raise HTTPException(404, f"tenant {tenant_id} not found")
    repo_rows = _backend.db.execute(
        "SELECT id FROM repos WHERE tenant_id = :t ORDER BY id LIMIT 1",
        {"t": tenant_id},
    )
    if not repo_rows:
        raise HTTPException(409, f"tenant {tenant_id} has no registered repos")
    repo_id = repo_rows[0]["id"]

    new_rows = _backend.db.execute(
        """
        INSERT INTO jobs (tenant_id, repo_id, ticket_title, ticket_body, status)
        VALUES (:t, :r, :title, :body, 'queued')
        RETURNING id
        """,
        {"t": tenant_id, "r": repo_id, "title": ticket_title, "body": ticket_body},
    )
    job_id = new_rows[0]["id"]

    if os.environ.get("DEVFORGE_BACKEND") == "aws":
        if not control_plane_url:
            raise HTTPException(
                500,
                "AWS mode dispatch requires control_plane_url; FastAPI route handler "
                "must pass `request.base_url` through to _spawn_run_ticket.",
            )
        handle = _dispatch_ecs_run_task(
            job_id=job_id, tenant_id=tenant_id, ticket_id=ticket_id,
            ticket_title=ticket_title, ticket_body=ticket_body,
            approval_token=approval_token, control_plane_url=control_plane_url,
        )
    else:
        handle = _dispatch_subprocess(
            job_id=job_id, tenant_id=tenant_id, ticket_id=ticket_id,
            ticket_title=ticket_title, ticket_body=ticket_body,
            approval_token=approval_token,
        )
    return job_id, handle


def _control_plane_url(request: Request) -> str:
    """Derive the public base URL of THIS control plane from the incoming
    request. Used to forward CONTROL_PLANE_API into the worker container
    via run_task overrides — avoids a TF Lambda↔API-Gateway cycle."""
    base = str(request.base_url)
    return base.rstrip("/")


@app.post("/jobs", status_code=202)
def submit_job(
    req: SubmitJobRequest,
    request: Request,
    _auth: dict = Depends(dual_auth),
):
    """Submit a ticket through the full crew. Pre-flights for secrets,
    pre-creates the jobs row so we can return its id, then spawns
    `scripts.run_ticket` via `_spawn_run_ticket` (mirroring the CLI
    invocation path).

    Returns 422 if the ticket itself contains live-shaped secrets.
    """
    from backend.safety import scan_secrets

    title_hits = scan_secrets(req.ticket_title)
    body_hits = scan_secrets(req.ticket_body)
    if title_hits or body_hits:
        findings = [
            {"where": where, "kind": kind, "summary": f"ticket {where} contains {kind}: {snippet}"}
            for where, hits in [("title", title_hits), ("body", body_hits)]
            for kind, snippet in hits
        ]
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "ticket contains real-shaped secret(s)",
                "findings": findings,
                "remediation": (
                    "Move the secret to environment variables or reference it by "
                    "name only. DevForge agents will not run on tickets with "
                    "embedded credentials."
                ),
            },
        )

    job_id, log_path = _spawn_run_ticket(
        tenant_id=req.tenant_id,
        ticket_id=req.ticket_id,
        ticket_title=req.ticket_title,
        ticket_body=req.ticket_body,
        approval_token=req.approval_token,
        control_plane_url=_control_plane_url(request),
    )
    return {"job_id": job_id, "log_path": log_path}


@app.post("/approvals/run", status_code=202)
def mint_approval_and_run(
    req: ApproveAndRunRequest,
    request: Request,
    _auth: dict = Depends(dual_auth),
):
    """Mint a ticket-bound approval token AND immediately spawn a fresh run.
    Returns the new job_id so the caller can navigate straight to its live
    event stream — no copy-paste of the token to a CLI.

    Authorization (#B2): either an admin token (CLI tooling) OR a Clerk user
    whose JWT identity maps to req.tenant_id via tenants.clerk_user_id /
    tenants.clerk_org_id. The browser never ships DEVFORGE_ADMIN_TOKEN.
    """
    _authorize_tenant_admin(_auth, req.tenant_id)
    from backend.safety import mint
    token = mint(command=req.command)
    job_id, _log = _spawn_run_ticket(
        tenant_id=req.tenant_id,
        ticket_id=req.ticket_id,
        ticket_title=req.ticket_title,
        ticket_body=req.ticket_body,
        approval_token=token,
        control_plane_url=_control_plane_url(request),
    )
    return {"token": token, "command": req.command, "job_id": job_id}


@app.get("/approvals/pending")
def list_pending_approvals(_auth: dict = Depends(dual_auth)):
    """Return all jobs with status='awaiting_approval' along with their
    derived approval_command (extracted from the latest approval_required
    event for each job). The frontend uses this to populate the approvals
    queue.
    """
    pending_jobs = _backend.db.execute(
        """
        SELECT id, tenant_id, ticket_title, ticket_body, created_at
        FROM jobs
        WHERE status = 'awaiting_approval'
        ORDER BY id DESC
        """
    )
    out: list[dict] = []
    for j in pending_jobs:
        evs = _backend.db.execute(
            """
            SELECT payload FROM job_events
            WHERE job_id = :j AND event = 'approval_required'
            ORDER BY id DESC
            LIMIT 1
            """,
            {"j": j["id"]},
        )
        approval_command = None
        if evs:
            try:
                payload = json.loads(evs[0]["payload"] or "{}")
                approval_command = payload.get("approval_command")
            except Exception:
                pass
        out.append({**j, "approval_command": approval_command})
    return {"pending": out}


@app.post("/jobs/{job_id}/approve")
def approve_job(
    job_id: int,
    req: ApproveRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Mint a one-time, command-bound, 5-minute approval token for `job_id`.

    DEPRECATED for migration / dependency-bump approvals: every `run_ticket`
    creates a fresh job_id, so a token bound to a specific job_id can only
    authorize one already-failed run. Prefer `POST /approvals` (no job_id),
    which command-binds the token; the orchestrator burns it on whatever
    job_id picks the same ticket back up. Kept for tests + the redteam
    harness which use strict job-bound mode.
    """
    _check_admin(x_admin_token)
    if not _backend.db.execute("SELECT id FROM jobs WHERE id=:j", {"j": job_id}):
        raise HTTPException(404, "job not found")

    from backend.safety import mint
    token = mint(job_id=job_id, command=req.command)
    return {"token": token, "job_id": job_id, "command": req.command}


@app.post("/approvals")
def approve_command(
    req: ApproveRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Mint a one-time, command-bound, 5-minute approval token (no job binding).

    Use this for the migration / dependency-bump flow:

        POST /approvals
        Headers: X-Admin-Token: <admin>
        Body:    {"command": "run_job:1:DEMO-1:Add migration adding age column to users"}

    The returned token authorizes ANY future run_ticket invocation that
    builds the same `command` string in its orchestrator. First call to
    verify_and_consume burns the token; replays + swaps still fail.
    """
    _check_admin(x_admin_token)
    from backend.safety import mint
    token = mint(command=req.command)  # job_id=None
    return {"token": token, "command": req.command}


# ============================================================================
# Existing endpoints
# ============================================================================

@app.get("/tenants/{tenant_id}/installation-token")
def get_installation_token(tenant_id: int, _auth: dict = Depends(dual_auth)):
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
