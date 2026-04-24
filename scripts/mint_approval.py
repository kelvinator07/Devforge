"""Mint an approval token for a destructive-ops job.

Usage:
    uv run python -m scripts.mint_approval <job_id> <command>
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: mint_approval.py <job_id> <command>")
    job_id = int(sys.argv[1])
    command = sys.argv[2]

    from backend.safety import mint
    token = mint(job_id=job_id, command=command)
    print(f"DEVFORGE_APPROVAL_TOKEN={token}")


if __name__ == "__main__":
    main()
