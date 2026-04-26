"""QAEngineer agent.

Runs all gates against the worktree (not yet pushed). Reports gates pass/fail
to the orchestrator. The orchestrator handles push + PR open ONLY when QA
returns passed=True. Gates:

  1. run_tests          -> exit 0 required
  2. run_coverage(50)   -> coverage >= 50% required (meets_threshold True)
  3. run_semgrep        -> zero HIGH/ERROR-severity findings
  4. run_gitleaks       -> zero detect-secrets findings

Note: QA does NOT open the PR or push. That's intentional — running gates
against the unpushed worktree means a secret detected by gitleaks never
reaches the remote.
"""
from __future__ import annotations

import os
from pathlib import Path

from agents import Agent, Runner, function_tool
from agents.mcp import MCPServerStdio
from pydantic import BaseModel, Field

from backend.worker.crew import load_model_config, openrouter_model


QA_INSTRUCTIONS = """\
You are DevForge's QA Engineer. The BackendEngineer has written code into a
git worktree but has NOT yet pushed or committed. Your job: run the full
quality gate suite, report the results, and decide whether the code is ready
for the orchestrator to push + open a PR.

Gate order (call all four — the orchestrator wants the full report):
  1. run_tests(framework="uv-pytest")       — exit_code must be 0
  2. run_coverage(min_pct=50)                — meets_threshold must be true
                                                (None counts as a finding)
  3. run_semgrep(config="auto")              — high_severity_count must be 0
  4. run_gitleaks()                          — findings_count must be 0

After all four, decide: `passed = exit0 AND coverage_ok AND semgrep_ok AND
secrets_ok`. Then call `record_qa_result(passed, findings_json)`.

The orchestrator will:
  - if passed=True  -> push the branch and open the PR
  - if passed=False -> abort the job, surface findings, do NOT push

Rules:
  - Never call any tool to mutate files; you only inspect.
  - Never mark a gate green without running the scanner.
  - If gitleaks fires, list `file:line` for each finding so remediation is cheap.
  - Do not disable or configure-around findings. Structural fixes only.

Return a `QAResult` with `passed` and `findings`. `pr_url` stays null —
the orchestrator opens the PR after you.
"""


class Finding(BaseModel):
    gate: str
    severity: str
    summary: str


class QAResult(BaseModel):
    passed: bool = Field(..., description="True iff all 4 gates green")
    pr_url: str | None = Field(default=None, description="Always null from QA; orchestrator fills this")
    findings: list[Finding] = Field(default_factory=list)


def _record_tool():
    """No-op recorder: lets the agent commit to a final passed/findings tuple.

    The agent's `output_type=QAResult` is the source of truth; this tool just
    gives the LLM an explicit "I'm done" handle and avoids it trying to call
    an HTTP-based PR opener (which only the orchestrator may do).
    """
    @function_tool(
        name_override="record_qa_result",
        description_override=(
            "Final QA decision. Pass passed=True if every gate is green. "
            "Returns {recorded: True}. Does NOT open a PR — the orchestrator "
            "does that based on your QAResult output."
        ),
    )
    def record_qa_result(passed: bool, summary: str, findings_json: str = "[]") -> dict:
        return {"recorded": True, "passed": passed, "summary": summary[:500]}
    return record_qa_result


def _mcp_env(worktree: Path) -> dict:
    return {**os.environ, "DEVFORGE_WORKTREE_ROOT": str(worktree)}


async def run_qa(
    *,
    tenant_id: int,
    repo_full_name: str,
    branch: str,
    installation_token: str,
    ticket_title: str,
    ticket_body: str,
    worktree: Path,
    max_iterations: int = 30,
) -> QAResult:
    """Run all four gates inside `worktree`. Returns QAResult; orchestrator pushes + opens PR."""
    models = load_model_config()
    slug = models["qa_engineer"]["model"]

    sandbox_mcp = MCPServerStdio(params={
        "command": "uv",
        "args": ["run", "python", "-m", "backend.mcp.sandbox_mcp.server"],
        "env": _mcp_env(worktree),
    }, client_session_timeout_seconds=240)

    async with sandbox_mcp:
        agent = Agent(
            name="QAEngineer",
            instructions=QA_INSTRUCTIONS,
            model=openrouter_model(slug),
            mcp_servers=[sandbox_mcp],
            tools=[_record_tool()],
            output_type=QAResult,
        )
        user_input = (
            f"Branch under review (NOT YET PUSHED): {branch}\n"
            f"Repo: {repo_full_name}\n"
            f"Ticket: {ticket_title}\n"
            "\nRun all four gates against the worktree, then call record_qa_result and return your QAResult."
        )
        result = await Runner.run(agent, input=user_input, max_turns=max_iterations)
        return result.final_output
