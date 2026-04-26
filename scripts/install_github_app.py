"""Capture a GitHub App installation_id and onboard it as a DevForge tenant.

Interactive flow:
  1. Prompt user for the App's install URL (shown on the App settings page).
  2. User visits it, installs on the target account, lands on a page whose URL contains ?installation_id=<N>.
  3. User pastes that installation_id here.
  4. Script calls control-plane /tenants/onboard.

Run from repo root:
    uv run python scripts/install_github_app.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main() -> None:
    # Match the convention used by run_ticket.py, redteam.py, etc.: prefer
    # .env.local (gitignored, holds secrets) and fall back to .env. Without
    # the .env.local load, DEVFORGE_ADMIN_TOKEN was missing and POST
    # /tenants/onboard 401'd.
    repo_root = Path(__file__).parent.parent
    load_dotenv(repo_root / ".env.local", override=False)
    load_dotenv(repo_root / ".env", override=False)

    api = os.environ.get("CONTROL_PLANE_API")
    if not api:
        sys.exit("CONTROL_PLANE_API not set in .env; run terraform/5_control_plane first")

    print("\nDevForge GitHub App installation")
    print("=" * 60)
    print()
    print("1. Visit your GitHub App settings page:")
    print("   https://github.com/settings/apps")
    print("2. Click your DevForge app name -> 'Install App'")
    print("3. Choose the account/org you want to be the demo tenant.")
    print("4. After install, the browser lands on a URL containing")
    print("   '?installation_id=NNNNNNN'. Copy that number.")
    print()

    installation_id = input("installation_id: ").strip()
    if not installation_id.isdigit():
        sys.exit("installation_id must be a positive integer")

    tenant_name = input("tenant_name (e.g. 'DevForge Demo'): ").strip() or "DevForge Demo"
    github_owner = input("github_owner (user or org the app was installed on): ").strip()
    if not github_owner:
        sys.exit("github_owner required")
    repo_full_name = input("repo_full_name (e.g. 'owner/devforge-demo-app'): ").strip()
    if "/" not in repo_full_name:
        sys.exit("repo_full_name must be 'owner/repo'")

    payload = {
        "tenant_name": tenant_name,
        "github_owner": github_owner,
        "repo_full_name": repo_full_name,
        "installation_id": int(installation_id),
    }

    print(f"\nPOST {api}/tenants/onboard")
    from backend.common import admin_headers
    cp_headers = admin_headers()
    r = httpx.post(f"{api}/tenants/onboard", json=payload,
                   headers=cp_headers, timeout=30.0)
    print(f"  status: {r.status_code}")
    print(f"  body:   {r.text}")
    r.raise_for_status()

    tenant_id = r.json()["tenant_id"]
    print(f"\nVerifying via GET /tenants/{tenant_id} ...")
    r2 = httpx.get(f"{api}/tenants/{tenant_id}", headers=cp_headers, timeout=15.0)
    r2.raise_for_status()
    print(f"  tenant: {r2.json()}")

    print(f"\nMinting a fresh installation token ...")
    r3 = httpx.get(f"{api}/tenants/{tenant_id}/installation-token",
                   headers=cp_headers, timeout=30.0)
    r3.raise_for_status()
    token = r3.json()["token"]
    print(f"  expires_at: {r3.json()['expires_at']}")

    print(f"\nUsing the token to GET /repos/{repo_full_name}/contents/README.md ...")
    gh = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/contents/README.md",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )
    if gh.status_code == 200:
        print(f"  OK: README.md exists, size {len(gh.text)} bytes of response")
    elif gh.status_code == 404:
        print(f"  OK: README.md not present (repo exists, token worked)")
    else:
        print(f"  status {gh.status_code}: {gh.text[:200]}")


if __name__ == "__main__":
    main()
