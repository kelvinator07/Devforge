"""BackendEngineer agent.

Consumes one TaskStep of kind=backend, works inside a per-job git worktree,
uses fs-mcp + sandbox-mcp + a local `search_codebase` tool, commits + pushes
a feature branch, returns a structured `EngineerResult`. NEVER opens a PR or
merges — Day 8's QA agent owns PR opening, and merging is human-only.

Prompts adapted from agents/3_crew/engineering_team/config/agents.yaml with
the DevForge sandbox + safety rules added.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agents import Agent, Runner, function_tool
from agents.mcp import MCPServerStdio
from pydantic import BaseModel, Field

from backend.worker.crew import load_model_config, openrouter_model
from backend.worker.schemas import TaskStep


BACKEND_ENGINEER_INSTRUCTIONS = """\
You are DevForge's Backend Engineer. You implement one step of a plan the
Engineering Lead handed to you, inside a sandboxed git worktree. You have
three groups of tools:

  - fs-mcp tools: read_file, write_file, list_dir, delete_file
    (All paths are relative to the worktree root. Escaping the root returns
     PathOutOfScope — don't try.)

  - sandbox-mcp tools: run_tests, run_linter, run_type_checker, run_build,
    git_status, list_changed_files
    (run_tests is your gate: do not declare done until it exits 0.)

  - search_codebase: semantic search over the tenant's indexed code. Use it
    whenever you need to find an existing function, class, or pattern.

Workflow:
  1. Read the step's `description` and `acceptance_criteria`.
  2. Use list_dir + read_file + search_codebase to confirm the exact files
     you'll touch. The plan's `files_likely_touched` is a hint, not a rule.
  3. Make the minimal change that satisfies ALL acceptance criteria.
  4. Call run_tests. If it fails, read the error, fix, and re-run — at most
     3 attempts. If still failing, return with success=False + a short note.
  5. When tests are green, return the result — DO NOT invoke any commit or
     push tool. The orchestrator commits on your behalf.

Rules:
  - No edits outside the worktree (fs-mcp enforces this; don't fight it).
  - No network calls.
  - No disabling tests, no `# noqa`, no `pragma: no cover`.
  - Match the project's existing style — indentation, imports, naming.
  - Do NOT run `run_build`. Do NOT create or modify uv.lock, .venv/, *.egg-info/,
    __pycache__/, .pytest_cache/ — they're build artifacts and must not reach the
    commit. Running `run_tests` is enough to validate correctness.

Return an `EngineerResult` with:
  - success: bool
  - summary: 1-3 sentence changelog line
  - files_changed: list of paths you wrote to
  - test_result: short description of the last test run
"""


class EngineerResult(BaseModel):
    success: bool = Field(..., description="True iff tests passed")
    summary: str = Field(..., description="1-3 sentence description of the change")
    files_changed: list[str] = Field(default_factory=list)
    test_result: str = Field(..., description="Short description of the last run_tests outcome")


def _search_codebase_tool(tenant_id: int):
    """Build a function_tool bound to this tenant's index."""

    @function_tool(name_override="search_codebase",
                   description_override="Semantic search over the tenant's indexed codebase. Returns up to k hits with file, lines, kind, text snippet.")
    def search_codebase(query: str, k: int = 6) -> list[dict]:
        from backend.ingest.index_tenant_repo import search_codebase as _search
        return _search(tenant_id, query, k=k)

    return search_codebase


def _mcp_env(worktree: Path) -> dict:
    return {**os.environ, "DEVFORGE_WORKTREE_ROOT": str(worktree)}


async def run_backend_step(
    tenant_id: int,
    step: TaskStep,
    worktree: Path,
    max_iterations: int = 50,
) -> EngineerResult:
    """Execute one backend step inside `worktree`. Returns EngineerResult."""
    models = load_model_config()
    slug = models["backend_engineer"]["model"]

    fs_mcp = MCPServerStdio(params={
        "command": "uv",
        "args": ["run", "python", "-m", "backend.mcp.fs_mcp.server"],
        "env": _mcp_env(worktree),
    }, client_session_timeout_seconds=60)
    sandbox_mcp = MCPServerStdio(params={
        "command": "uv",
        "args": ["run", "python", "-m", "backend.mcp.sandbox_mcp.server"],
        "env": _mcp_env(worktree),
    }, client_session_timeout_seconds=60)

    async with fs_mcp, sandbox_mcp:
        agent = Agent(
            name="BackendEngineer",
            instructions=BACKEND_ENGINEER_INSTRUCTIONS,
            model=openrouter_model(slug),
            mcp_servers=[fs_mcp, sandbox_mcp],
            tools=[_search_codebase_tool(tenant_id)],
            output_type=EngineerResult,
        )
        user_input = (
            f"STEP #{step.id}\n"
            f"description: {step.description}\n"
            f"acceptance_criteria:\n"
            + "\n".join(f"  - {c}" for c in step.acceptance_criteria)
            + "\n\nfiles_likely_touched: "
            + ", ".join(step.files_likely_touched or ["(none specified)"])
        )
        result = await Runner.run(agent, input=user_input, max_turns=max_iterations)
        return result.final_output


# Artifacts we refuse to commit even if the agent accidentally creates them.
_JUNK_PATTERNS = [
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "*.egg-info",
    "uv.lock",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".coverage",
    ".coverage.*",
    "coverage.xml",
    "htmlcov",
    ".tox",
    ".cache",
]


def _scrub_worktree(worktree: Path) -> list[str]:
    """Remove common build artifacts before staging. Returns paths removed."""
    import fnmatch
    import shutil

    removed: list[str] = []
    for item in worktree.rglob("*"):
        rel = str(item.relative_to(worktree))
        for pat in _JUNK_PATTERNS:
            if fnmatch.fnmatch(item.name, pat) or rel.startswith(pat + "/") or rel == pat:
                if item.exists():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                    removed.append(rel)
                break
    return removed


def commit_and_push(worktree: Path, branch: str, remote_url: str, commit_message: str) -> dict:
    """Commit staged changes on `branch` and push to remote.

    Returns a dict that always has `pushed: bool`. Never raises on a non-fatal
    failure (no changes / git rejection / push protection). The orchestrator
    inspects the dict and emits a structured event.

    Common failure modes captured in `reason`:
      - "no changes to commit"
      - "push rejected" (typically GitHub push-protection caught a secret)
      - "git error" (any other git failure)
    """
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "DevForge Bot",
           "GIT_AUTHOR_EMAIL": "bot@devforge.app",
           "GIT_COMMITTER_NAME": "DevForge Bot",
           "GIT_COMMITTER_EMAIL": "bot@devforge.app"}

    scrubbed = _scrub_worktree(worktree)

    try:
        subprocess.run(["git", "add", "-A"], cwd=worktree, check=True, env=env,
                       capture_output=True)
    except subprocess.CalledProcessError as exc:
        return {"pushed": False, "scrubbed": scrubbed, "reason": "git error",
                "stage": "add", "stderr": (exc.stderr or b"").decode("utf-8", "replace")[-1000:]}

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree, env=env)
    if diff.returncode == 0:
        return {"pushed": False, "reason": "no changes to commit", "scrubbed": scrubbed}

    try:
        subprocess.run(["git", "commit", "-m", commit_message],
                       cwd=worktree, check=True, env=env, capture_output=True)
    except subprocess.CalledProcessError as exc:
        return {"pushed": False, "scrubbed": scrubbed, "reason": "git error",
                "stage": "commit", "stderr": (exc.stderr or b"").decode("utf-8", "replace")[-1000:]}

    try:
        subprocess.run(["git", "push", "--set-upstream", remote_url, branch],
                       cwd=worktree, check=True, env=env, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", "replace")
        # GitHub push protection emits a clear marker.
        rejected_for_secret = (
            "GH013" in stderr
            or "push protection" in stderr.lower()
            or "secret detected" in stderr.lower()
        )
        return {
            "pushed": False,
            "branch": branch,
            "scrubbed": scrubbed,
            "reason": "push rejected by github push-protection" if rejected_for_secret else "push rejected",
            "stage": "push",
            "stderr": stderr[-1500:],
            "rejected_for_secret": rejected_for_secret,
        }

    return {"pushed": True, "branch": branch, "scrubbed": scrubbed}
