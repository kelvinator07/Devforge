"""QAEngineer agent.

Runs all gates against a worktree + a branch that BackendEngineer has already
committed to. Opens the PR ONLY when every gate is green. Gates:

  1. run_tests          -> exit 0 required
  2. run_coverage(50)   -> coverage >= 50% required (meets_threshold True)
  3. run_semgrep        -> zero HIGH/ERROR-severity findings
  4. run_gitleaks       -> zero detect-secrets findings

PR opening is handled by a local function_tool `create_pr` that talks to the
GitHub REST API with a fresh installation token. The agent MUST only call
`submit_for_review`, which wraps `create_pr` behind a passed-all-gates check.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from agents import Agent, Runner, function_tool
from agents.mcp import MCPServerStdio
from pydantic import BaseModel, Field

from backend.worker.crew import load_model_config, openrouter_model


QA_INSTRUCTIONS = """\
You are DevForge's QA Engineer. A BackendEngineer has already committed code
to a feature branch. Your job: run the full quality gate suite, report the
results, and open a Pull Request IF AND ONLY IF every gate is green.

Gate order (call all four even if one fails — the user wants the full report):
  1. run_tests(framework="uv-pytest")       — exit_code must be 0
  2. run_coverage(min_pct=50)                — meets_threshold must be true
                                                (None = fail if coverage unavailable,
                                                 flag it as a finding)
  3. run_semgrep(config="auto")              — high_severity_count must be 0
  4. run_gitleaks()                          — findings_count must be 0

After all four, decide: `passed = exit0 AND coverage_ok AND semgrep_ok AND
secrets_ok`. Then call `submit_for_review` with the final decision + findings.

`submit_for_review` will open the PR if `passed=True`, or refuse if not. The
refusal writes the findings back into your output so Backend can re-run.

Rules:
  - Never call any tool to mutate files; you only inspect.
  - Never mark a gate green without running the scanner.
  - If gitleaks fires, list the file:line of each finding so remediation is cheap.
  - Do not disable or configure-around findings. Structural fixes only.

Return a `QAResult` with `passed`, `pr_url` (if opened), and `findings`.
"""


class Finding(BaseModel):
    gate: str
    severity: str
    summary: str


class QAResult(BaseModel):
    passed: bool = Field(..., description="True iff all 4 gates green")
    pr_url: str | None = Field(default=None, description="Set when passed and PR opened")
    findings: list[Finding] = Field(default_factory=list)


def _submit_tool(
    *,
    tenant_id: int,
    repo_full_name: str,
    branch: str,
    installation_token: str,
    ticket_title: str,
    ticket_body: str,
):
    """Build the submit_for_review function_tool bound to this job's context.

    The tool opens a PR via GitHub REST API only when passed=True. We use a
    closure so the LLM can't accidentally pass the wrong repo/branch.
    """
    @function_tool(
        name_override="submit_for_review",
        description_override=(
            "Submit the QA result. If passed=True, opens a PR on the feature "
            "branch; if passed=False, records the findings and does NOT open "
            "a PR (Backend will re-run). Returns {pr_url | None, recorded: True}."
        ),
    )
    def submit_for_review(passed: bool, summary: str, findings_json: str = "[]") -> dict:
        if not passed:
            return {"pr_url": None, "recorded": True, "passed": False, "summary": summary}
        # Open the PR. Base is the repo's default branch (main for the demo).
        body_text = (
            f"{ticket_body}\n\n"
            f"---\n"
            f"🤖 Opened by DevForge QAEngineer after all 4 gates passed.\n"
            f"{summary}\n"
        )
        r = httpx.post(
            f"https://api.github.com/repos/{repo_full_name}/pulls",
            headers={
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": ticket_title,
                "head": branch,
                "base": "main",
                "body": body_text,
            },
            timeout=30.0,
        )
        if r.status_code in (200, 201):
            return {"pr_url": r.json()["html_url"], "recorded": True, "passed": True}
        # Common case: PR already exists for this head -> fetch it.
        if r.status_code == 422 and "already exists" in r.text.lower():
            q = httpx.get(
                f"https://api.github.com/repos/{repo_full_name}/pulls",
                headers={"Authorization": f"token {installation_token}"},
                params={"head": f"{repo_full_name.split('/')[0]}:{branch}", "state": "open"},
                timeout=15.0,
            )
            if q.status_code == 200 and q.json():
                return {"pr_url": q.json()[0]["html_url"], "recorded": True, "passed": True}
        return {
            "pr_url": None,
            "recorded": True,
            "passed": True,
            "error": f"PR open failed: {r.status_code} {r.text[:300]}",
        }

    return submit_for_review


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
    """Run all four gates inside `worktree`. Returns QAResult with pr_url on all-green."""
    models = load_model_config()
    slug = models["qa_engineer"]["model"]

    sandbox_mcp = MCPServerStdio(params={
        "command": "uv",
        "args": ["run", "python", "-m", "backend.mcp.sandbox_mcp.server"],
        "env": _mcp_env(worktree),
    })

    async with sandbox_mcp:
        submit_tool = _submit_tool(
            tenant_id=tenant_id,
            repo_full_name=repo_full_name,
            branch=branch,
            installation_token=installation_token,
            ticket_title=ticket_title,
            ticket_body=ticket_body,
        )
        agent = Agent(
            name="QAEngineer",
            instructions=QA_INSTRUCTIONS,
            model=openrouter_model(slug),
            mcp_servers=[sandbox_mcp],
            tools=[submit_tool],
            output_type=QAResult,
        )
        user_input = (
            f"Branch under review: {branch}\n"
            f"Repo: {repo_full_name}\n"
            f"Ticket: {ticket_title}\n"
            "\nRun all four gates, then submit_for_review."
        )
        result = await Runner.run(agent, input=user_input, max_turns=max_iterations)
        return result.final_output
