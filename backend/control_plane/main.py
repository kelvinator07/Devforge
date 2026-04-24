"""DevForge control plane — FastAPI.

Runs locally (uvicorn) or on AWS Lambda (via Mangum). Backend chosen by
DEVFORGE_BACKEND=local|aws.

Day 3 surface:
  - GET  /health
  - POST /tenants/onboard
  - GET  /tenants/{tenant_id}
  - GET  /tenants/{tenant_id}/installation-token
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
