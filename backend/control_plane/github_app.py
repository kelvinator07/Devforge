"""GitHub App authentication: JWT signing + installation-token minting.

Backend-aware: reads the private key via `backend.common`, so the same code
works locally (env var / file path) and on AWS (Secrets Manager).

Refs:
  - https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app
  - https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app
"""
from __future__ import annotations

import time

import httpx
import jwt

from backend.common import get_backend


GITHUB_API = "https://api.github.com"


def get_private_key() -> str:
    return get_backend().secrets.get("github-app-private-key")


def make_app_jwt(private_key_pem: str, app_id: str | int) -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": str(app_id),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def mint_installation_token(app_jwt: str, installation_id: str | int) -> tuple[str, str]:
    url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"
    r = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15.0,
    )
    r.raise_for_status()
    data = r.json()
    return data["token"], data["expires_at"]


def installation_token_for(app_id: str | int, installation_id: str | int) -> tuple[str, str]:
    pk = get_private_key()
    app_jwt = make_app_jwt(pk, app_id)
    return mint_installation_token(app_jwt, installation_id)
