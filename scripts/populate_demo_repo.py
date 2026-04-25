"""Upload the demo FastAPI app content to the tenant's repo using the GitHub App.

Uses the Contents RW permission on the GitHub App to PUT files directly through
the GitHub REST API. This replaces the `gh repo create` path in
seed_demo_tenant.py (which requires a valid user token in gh).

Usage:
    uv run python -m scripts.populate_demo_repo <tenant_id>
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=False)
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


FILES = {
    "README.md": "# devforge-demo-app\n\nTiny FastAPI app that DevForge agents work on.\n\n## Run\n\n    uv sync\n    uv run uvicorn app.main:app --reload\n",
    "pyproject.toml": """[project]
name = "devforge-demo-app"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "httpx>=0.27.0",
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "coverage>=7.4",
]

[tool.pytest.ini_options]
pythonpath = ["."]
""",
    "app/__init__.py": "",
    "app/main.py": '''"""devforge-demo-app: tiny FastAPI service used by DevForge agents as a test target."""
from fastapi import FastAPI

app = FastAPI(title="devforge-demo-app")

USERS = [
    {"id": 1, "name": "Ada"},
    {"id": 2, "name": "Linus"},
    {"id": 3, "name": "Grace"},
]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/users")
def list_users():
    return USERS


@app.get("/users/{user_id}")
def get_user(user_id: int):
    for u in USERS:
        if u["id"] == user_id:
            return u
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="user not found")
''',
    "tests/__init__.py": "",
    "tests/test_main.py": '''from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_users():
    r = client.get("/users")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_get_user_ok():
    r = client.get("/users/1")
    assert r.status_code == 200
    assert r.json()["name"] == "Ada"


def test_get_user_404():
    r = client.get("/users/999")
    assert r.status_code == 404
''',
    ".gitignore": (
        ".venv/\nvenv/\n__pycache__/\n*.pyc\n.pytest_cache/\n"
        ".ruff_cache/\n.mypy_cache/\n*.egg-info/\nuv.lock\n"
        "dist/\nbuild/\n.next/\nnode_modules/\n"
    ),
}


def put_file(session: httpx.Client, repo: str, path: str, content: str, message: str) -> None:
    # Fetch current sha if the file exists so we can update instead of creating.
    existing = session.get(f"/repos/{repo}/contents/{path}")
    sha = existing.json()["sha"] if existing.status_code == 200 else None

    body = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
    }
    if sha:
        body["sha"] = sha
    r = session.put(f"/repos/{repo}/contents/{path}", json=body)
    if r.status_code not in (200, 201):
        raise SystemExit(f"PUT {path} failed: {r.status_code} {r.text[:300]}")
    print(f"  {'updated' if sha else 'created'}: {path}")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: populate_demo_repo.py <tenant_id>")
    tenant_id = int(sys.argv[1])
    api = os.environ.get("CONTROL_PLANE_API", "http://localhost:8001")

    from backend.common import admin_headers
    cp_headers = admin_headers()
    t = httpx.get(f"{api}/tenants/{tenant_id}", headers=cp_headers, timeout=15.0)
    t.raise_for_status()
    repo = t.json()["repos"][0]["full_name"]

    tok = httpx.get(f"{api}/tenants/{tenant_id}/installation-token",
                    headers=cp_headers, timeout=30.0)
    tok.raise_for_status()
    token = tok.json()["token"]

    session = httpx.Client(
        base_url="https://api.github.com",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )

    print(f"populating {repo}")
    for path, content in FILES.items():
        put_file(session, repo, path, content, "devforge: seed demo FastAPI app")

    print("\ndone. next:")
    print(f"  uv run python -m scripts.index_repo {tenant_id}")


if __name__ == "__main__":
    main()
