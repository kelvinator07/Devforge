"""MigrationEngineer agent.

Same tool surface as BackendEngineer (fs-mcp + sandbox-mcp + search_codebase),
but the system prompt forbids running migrations or applying schema changes.
The agent ONLY stages SQL files in a `migrations/` directory; the human
applies them after merging the PR.

Migration steps always have `requires_human_approval=true` enforced upstream
by classify_plan_step + the orchestrator's approval-token check.
"""
from __future__ import annotations

import os
from pathlib import Path

from agents import Agent, Runner
from agents.mcp import MCPServerStdio

from backend.worker.backend_engineer import EngineerResult, _search_codebase_tool
from backend.worker.crew import load_model_config, openrouter_model
from backend.worker.schemas import TaskStep


MIGRATION_ENGINEER_INSTRUCTIONS = """\
You are DevForge's Migration Engineer. You stage SQL migration files for a
database schema change — but you NEVER apply them. The human reviews the
staged SQL in the resulting PR and applies it after merging.

Your tools (same as Backend Engineer): fs-mcp, sandbox-mcp, search_codebase.

Workflow:
  1. Read the step's `description` + `acceptance_criteria` carefully.
  2. Use list_dir to find any existing `migrations/` or `db/migrations/`
     directory. If none exists at the project root, create `migrations/`.
  3. Use search_codebase to find the existing schema (tables, columns).
  4. Write a NEW SQL file at `migrations/<NNN>_<slug>.sql` where NNN is the
     next available 3-digit prefix. The file should:
       - Be idempotent (CREATE TABLE IF NOT EXISTS, ALTER TABLE ... IF NOT EXISTS).
       - Include a clear `-- Description:` comment block at the top.
       - Use standard ANSI SQL where possible.
  5. If the existing schema uses a particular dialect (Postgres, SQLite),
     match it. The DevForge demo repo uses Postgres.
  6. Update any documentation that references the schema (e.g. README schema
     table, ER diagram) — keep it in sync.

Hard rules:
  - Do NOT run `alembic`, `migrate`, `psql`, `sqlite3`, or any tool that
    APPLIES the migration. Only WRITE the SQL file.
  - Do NOT call run_build (forbidden) or run_tests against the migration —
    tests run later by QA against the existing schema.
  - Do NOT delete or modify existing migration files (they may already have
    been applied to production).
  - Do NOT include destructive ops (DROP TABLE on existing populated tables,
    TRUNCATE, irreversible column drops without an IF EXISTS guard).

Return an `EngineerResult` with:
  - success: True if you wrote the SQL file successfully
  - summary: 1-3 sentences describing the schema change
  - files_changed: list including the migration file path
  - test_result: "migration staged; not applied" (don't run tests here)
"""


def _mcp_env(worktree: Path) -> dict:
    return {**os.environ, "DEVFORGE_WORKTREE_ROOT": str(worktree)}


async def run_migration_step(
    tenant_id: int,
    step: TaskStep,
    worktree: Path,
    max_iterations: int = 40,
) -> EngineerResult:
    """Stage migration SQL for `step` inside `worktree`. Never applies."""
    models = load_model_config()
    slug = models["backend_engineer"]["model"]  # reuse backend slot — same model is fine

    fs_mcp = MCPServerStdio(params={
        "command": "uv",
        "args": ["run", "python", "-m", "backend.mcp.fs_mcp.server"],
        "env": _mcp_env(worktree),
    })
    sandbox_mcp = MCPServerStdio(params={
        "command": "uv",
        "args": ["run", "python", "-m", "backend.mcp.sandbox_mcp.server"],
        "env": _mcp_env(worktree),
    })

    async with fs_mcp, sandbox_mcp:
        agent = Agent(
            name="MigrationEngineer",
            instructions=MIGRATION_ENGINEER_INSTRUCTIONS,
            model=openrouter_model(slug),
            mcp_servers=[fs_mcp, sandbox_mcp],
            tools=[_search_codebase_tool(tenant_id)],
            output_type=EngineerResult,
        )
        user_input = (
            f"MIGRATION STEP #{step.id}\n"
            f"description: {step.description}\n"
            f"acceptance_criteria:\n"
            + "\n".join(f"  - {c}" for c in step.acceptance_criteria)
            + "\n\nfiles_likely_touched: "
            + ", ".join(step.files_likely_touched or ["(none specified)"])
            + "\n\nReminder: stage the SQL file. Do not apply the migration."
        )
        result = await Runner.run(agent, input=user_input, max_turns=max_iterations)
        return result.final_output
