"""Seed a toy Python FastAPI repo on your GitHub account and install the DevForge App on it.

Prerequisites:
  - `gh` CLI installed + authenticated (gh auth status) as the account that owns the App.

Run:
    uv run python scripts/seed_demo_tenant.py

After the repo exists and the DevForge App has been installed on it, run
`scripts/install_github_app.py` to capture the installation_id and register the tenant.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


REPO_NAME = "devforge-demo-app"
DEFAULT_BRANCH = "main"


DEMO_FILES = {
    "README.md": """# devforge-demo-app

A tiny FastAPI app used as the reference repo for DevForge agents.

## Run

    uv sync
    uv run uvicorn app.main:app --reload
""",
    "pyproject.toml": """[project]
name = "devforge-demo-app"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["fastapi>=0.115.0", "uvicorn>=0.30.0"]
""",
    "app/__init__.py": "",
    "app/main.py": """from fastapi import FastAPI

app = FastAPI(title="devforge-demo-app")

USERS = [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Linus"}]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/users")
def users():
    return USERS
""",
    "tests/__init__.py": "",
    "tests/test_main.py": """from fastapi.testclient import TestClient

from app.main import app


def test_health():
    c = TestClient(app)
    assert c.get("/health").json() == {"status": "ok"}


def test_users():
    c = TestClient(app)
    r = c.get("/users")
    assert r.status_code == 200
    assert len(r.json()) == 2
""",
    ".gitignore": """.venv/
__pycache__/
*.pyc
""",
}


def run(cmd: list[str], cwd: Path | None = None) -> str:
    print(f"  $ {' '.join(cmd)}", flush=True)
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def main() -> None:
    # 1. Check gh auth
    try:
        subprocess.check_call(["gh", "auth", "status"], stdout=subprocess.DEVNULL)
    except Exception:
        sys.exit("gh CLI not authenticated. Run `gh auth login` first.")

    who = run(["gh", "api", "user", "-q", ".login"])
    print(f"\nAuthenticated as: {who}")

    # 2. Does repo already exist?
    try:
        run(["gh", "repo", "view", f"{who}/{REPO_NAME}"])
        print(f"Repo {who}/{REPO_NAME} already exists, skipping creation.")
    except subprocess.CalledProcessError:
        print(f"\nCreating {who}/{REPO_NAME} ...")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / REPO_NAME
            root.mkdir()
            for rel, content in DEMO_FILES.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            run(["git", "init", "-b", DEFAULT_BRANCH], cwd=root)
            run(["git", "add", "."], cwd=root)
            run(["git", "commit", "-m", "devforge-demo-app seed"], cwd=root)
            run([
                "gh", "repo", "create", f"{who}/{REPO_NAME}",
                "--source", str(root),
                "--public",
                "--push",
                "--description", "DevForge demo repo - seeded automatically",
            ])

    print(f"\nRepo URL: https://github.com/{who}/{REPO_NAME}")
    print(f"\nNext: install the DevForge GitHub App on {who}/{REPO_NAME} only, then run:")
    print(f"    uv run python scripts/install_github_app.py")


if __name__ == "__main__":
    main()
