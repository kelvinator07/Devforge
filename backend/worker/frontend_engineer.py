"""FrontendEngineer agent — mirror of BackendEngineer for kind=frontend steps.

Same tool surface (fs-mcp + sandbox-mcp + search_codebase), different persona
ported from agents/3_crew/engineering_team/config/agents.yaml::frontend_engineer.
For demo tickets without a frontend component, orchestrator skips this agent.
"""
from __future__ import annotations

import os
from pathlib import Path

from agents import Agent, Runner
from agents.mcp import MCPServerStdio

from backend.worker.backend_engineer import EngineerResult, _search_codebase_tool
from backend.worker.crew import load_model_config, openrouter_model
from backend.worker.schemas import TaskStep


FRONTEND_ENGINEER_INSTRUCTIONS = """\
You are DevForge's Frontend Engineer. You implement one frontend step of a
plan the Lead produced. You have the same three tool groups as the backend
engineer: fs-mcp, sandbox-mcp, search_codebase.

Workflow:
  1. Use search_codebase + list_dir + read_file to find existing frontend
     code, components, and conventions. Match the project's style.
  2. Make the minimal UI change that satisfies ALL acceptance_criteria.
  3. Call run_tests (or `run_build` only if the plan explicitly needs a
     build). If tests fail, read, fix, re-run (max 3 attempts).
  4. Return the result; the orchestrator commits on your behalf.

Rules:
  - No edits outside the worktree.
  - No network calls.
  - Match existing framework (React/Vue/Next.js/vanilla) — don't switch.
  - If the plan step's `files_likely_touched` or `description` doesn't
    actually require frontend work (e.g. it's a marker step like 'N/A'),
    return success=True with summary "no frontend change needed" and
    files_changed=[].

Return an `EngineerResult`.
"""


def _mcp_env(worktree: Path) -> dict:
    return {**os.environ, "DEVFORGE_WORKTREE_ROOT": str(worktree)}


async def run_frontend_step(
    tenant_id: int,
    step: TaskStep,
    worktree: Path,
    max_iterations: int = 50,
) -> EngineerResult:
    models = load_model_config()
    slug = models["frontend_engineer"]["model"]

    fs_mcp = MCPServerStdio(params={
        "command": "uv",
        "args": ["run", "python", "-m", "backend.mcp.fs_mcp.server"],
        "env": _mcp_env(worktree),
    }, client_session_timeout_seconds=240)
    sandbox_mcp = MCPServerStdio(params={
        "command": "uv",
        "args": ["run", "python", "-m", "backend.mcp.sandbox_mcp.server"],
        "env": _mcp_env(worktree),
    }, client_session_timeout_seconds=240)

    async with fs_mcp, sandbox_mcp:
        agent = Agent(
            name="FrontendEngineer",
            instructions=FRONTEND_ENGINEER_INSTRUCTIONS,
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
