"""Smoke-test devforge-fs-mcp + devforge-sandbox-mcp as stdio MCP servers.

Spawns each server, lists its tools, calls a happy-path tool, and confirms
fs-mcp rejects a path that escapes the worktree root (PathOutOfScope).

Usage (assumes tenant 1's repo has been populated + the demo repo exists):
    uv run python -m scripts.verify_mcps
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from agents.mcp import MCPServerStdio
from dotenv import load_dotenv


_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)


FS_CMD = {
    "command": "uv",
    "args": ["run", "python", "-m", "backend.mcp.fs_mcp.server"],
}
SANDBOX_CMD = {
    "command": "uv",
    "args": ["run", "python", "-m", "backend.mcp.sandbox_mcp.server"],
}


async def verify_fs(worktree: Path) -> None:
    env = {**os.environ, "DEVFORGE_WORKTREE_ROOT": str(worktree)}
    srv = MCPServerStdio(params={**FS_CMD, "env": env})
    async with srv:
        tools = await srv.list_tools()
        print(f"[fs] tools: {[t.name for t in tools]}")

        # happy path
        r = await srv.call_tool("list_dir", {"path": "."})
        print(f"[fs] list_dir('.') -> {r.content[0].text if r.content else r}")

        # write_file + read_file round trip
        await srv.call_tool("write_file", {"path": "hello.txt", "content": "hi devforge"})
        r = await srv.call_tool("read_file", {"path": "hello.txt"})
        body = r.content[0].text if r.content else ""
        assert "hi devforge" in body, body
        print(f"[fs] read_file('hello.txt') round-trip OK")

        # scope violation
        r = await srv.call_tool("read_file", {"path": "../../etc/passwd"})
        text = r.content[0].text if r.content else ""
        assert "PathOutOfScope" in text or r.isError, f"scope not enforced: {r}"
        print(f"[fs] scope enforcement OK: {text.splitlines()[0][:120]}")


async def verify_sandbox(worktree: Path) -> None:
    env = {**os.environ, "DEVFORGE_WORKTREE_ROOT": str(worktree)}
    srv = MCPServerStdio(params={**SANDBOX_CMD, "env": env})
    async with srv:
        tools = await srv.list_tools()
        print(f"[sandbox] tools: {[t.name for t in tools]}")

        r = await srv.call_tool("git_status", {})
        text = r.content[0].text if r.content else ""
        print(f"[sandbox] git_status -> {text.splitlines()[0] if text else '(empty)'}")

        # unallowed build command is rejected
        r = await srv.call_tool("run_build", {"command": "rm -rf /"})
        text = r.content[0].text if r.content else ""
        assert "allowlist" in text or r.isError, f"build allowlist failed: {r}"
        print(f"[sandbox] build allowlist OK: {text.splitlines()[0][:120]}")


async def main() -> None:
    # Use the existing cached worktree if index_repo ran it, else make a temp scratch one.
    data_dir = Path(os.environ.get("DEVFORGE_DATA_DIR") or _REPO_ROOT / "data")
    worktree_root = data_dir / "worktrees"
    worktree_root.mkdir(parents=True, exist_ok=True)

    # Scratch git worktree for the smoke test (fresh, not tied to any tenant).
    with tempfile.TemporaryDirectory(prefix="devforge-verify-") as td:
        wt = Path(td) / "scratch"
        wt.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
        (wt / "README.md").write_text("# scratch\n")
        subprocess.run(["git", "add", "."], cwd=wt, check=True)
        subprocess.run(
            ["git", "-c", "user.email=ci@devforge.local", "-c", "user.name=DevForge CI",
             "commit", "-q", "-m", "init"],
            cwd=wt, check=True,
        )

        print(f"\n=== verifying fs-mcp against {wt} ===")
        await verify_fs(wt)

        print(f"\n=== verifying sandbox-mcp against {wt} ===")
        await verify_sandbox(wt)

    print("\nBoth MCPs responding + enforcing their guardrails.")


if __name__ == "__main__":
    asyncio.run(main())
