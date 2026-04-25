"""Direct QA-gate test — seeds a real secret in a worktree and runs gitleaks
without going through the LLM agent.

Why this exists: in Scene 2 of TESTING.md, the killer-demo ticket asks the
BackendEngineer to write a literal Stripe key into the code. Modern LLMs
(GPT-4o, Sonnet) silently sanitize that — they write `"your-stripe-key-here"`
or similar — so the file gitleaks ends up scanning has no real secret. The
killer demo then misleadingly "passes" via LLM compliance, not the gate.

This script proves the gate works STRUCTURALLY by skipping the agent entirely:
it prepares a per-tenant worktree, writes a file containing a real
secret-shaped string, then invokes the same `detect-secrets` binary that
sandbox-mcp's `run_gitleaks` tool calls. If findings > 0, the gate is sound.

Usage:
    uv run python -m scripts.test_qa_gate_direct <tenant_id>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)


# Real-shaped secrets across detector families. Each one is a fake test value
# that triggers a specific detect-secrets plugin.
SEEDED_SECRETS = {
    "stripe_live": 'STRIPE_KEY = "sk_live_4eC39HqLyjWDarjtT1zdp7dcXxK7VbG28"',
    "openai":      'OPENAI_API_KEY = "sk-proj-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789aBcDeFgHiJkLmNoPq"',
    "github_pat":  'GITHUB_TOKEN = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789ab"',
    "aws_access":  'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"',
}


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: test_qa_gate_direct.py <tenant_id>")
    tenant_id = int(sys.argv[1])

    api = "http://localhost:8001"

    # Reuse the orchestrator's worktree manager — we want exactly the same
    # filesystem layout the agents work in.
    t = httpx.get(f"{api}/tenants/{tenant_id}", timeout=15.0)
    t.raise_for_status()
    repo_full_name = t.json()["repos"][0]["full_name"]

    tok = httpx.get(f"{api}/tenants/{tenant_id}/installation-token", timeout=30.0)
    tok.raise_for_status()
    installation_token = tok.json()["token"]

    from backend.worker.worktree import prepare_worktree

    print(f"=== preparing fresh worktree for {repo_full_name} ===")
    wt = prepare_worktree(tenant_id, repo_full_name, installation_token,
                          branch_name=f"devforge/qa-gate-test-{__import__('os').getpid()}")
    print(f"  worktree: {wt.worktree_path}")
    print(f"  branch:   {wt.branch}")

    failures: list[str] = []
    try:
        for label, line in SEEDED_SECRETS.items():
            target = wt.worktree_path / "app" / "secrets_demo.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"# auto-seeded by test_qa_gate_direct.py\n{line}\n")
            # Stage so detect-secrets sees it as part of the project.
            subprocess.run(["git", "add", "app/secrets_demo.py"],
                           cwd=wt.worktree_path, check=True)

            print(f"\n--- seed: {label} ---")
            r = subprocess.run(
                ["detect-secrets", "scan", "--all-files"],
                cwd=wt.worktree_path, capture_output=True, text=True,
            )
            try:
                data = json.loads(r.stdout or "{}")
            except Exception:
                data = {}
            findings = sum(len(v) for v in (data.get("results") or {}).values())
            print(f"  findings: {findings}")
            for fp, items in (data.get("results") or {}).items():
                for it in items:
                    print(f"    {fp} line {it.get('line_number')}: {it.get('type')}")

            if findings == 0:
                failures.append(f"{label}: detect-secrets returned 0 findings (gate would pass)")

        # Cleanup the seeded file before the worktree is destroyed.
        target = wt.worktree_path / "app" / "secrets_demo.py"
        if target.exists():
            target.unlink()
            subprocess.run(["git", "rm", "--cached", "app/secrets_demo.py"],
                           cwd=wt.worktree_path, check=False, capture_output=True)
    finally:
        wt.cleanup()

    print()
    if failures:
        print(f"FAIL — gate missed {len(failures)} secret variant(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"PASS — gate caught all {len(SEEDED_SECRETS)} secret variants.")


if __name__ == "__main__":
    main()
