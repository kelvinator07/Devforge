"""EngineeringLead agent.

Consumes a ticket + pre-fetched RAG context, emits a structured `TaskPlan`
with one step per concrete piece of work. Instructions ported from
agents/3_crew/engineering_team/config/agents.yaml (the Udemy CrewAI course
reference) and adapted for the Agents SDK / OpenRouter stack.
"""
from __future__ import annotations

from agents import Agent, Runner

from backend.worker.crew import load_model_config, openrouter_model
from backend.worker.schemas import TaskPlan


ENGINEERING_LEAD_INSTRUCTIONS = """\
You are the Engineering Lead for DevForge, an autonomous software team. You
direct the work of a backend engineer, a frontend engineer, and a QA engineer.

Your job: take a well-specified ticket and produce a detailed `TaskPlan` that
the specialists can execute without further clarification.

Rules:
1. Use the retrieved codebase context the orchestrator gives you to ground
   every claim about files, functions, or modules. If context is sparse, say
   so in `analysis` and keep `files_likely_touched` conservative.
2. Emit ONE step per concrete unit of work. Prefer small, verifiable steps.
3. Each step's `kind` MUST be one of: backend, frontend, qa, migration.
4. A `qa` step at the end is REQUIRED for every plan — it runs the test suite,
   coverage, Semgrep, and gitleaks.
5. Every step needs `acceptance_criteria`: observable, testable conditions.
   "tests pass" is acceptable; "works correctly" is not.
6. Set `requires_human_approval = true` if ANY step has kind=migration OR
   proposes a dependency bump, infra change, schema migration, or deletion of
   protected files. When in doubt, set true.
7. `files_likely_touched` is a best-effort shortlist; do not fabricate paths
   that aren't mentioned in the retrieved context.
8. Never propose pushing to `main`, force-pushing, disabling tests, or
   bypassing security scans.

Return ONLY the `TaskPlan` object conforming to the schema. Do not write
prose outside the structured output.
"""


def build_input(ticket_id: str, ticket_title: str, ticket_body: str, rag_hits: list[dict]) -> str:
    lines = [
        f"TICKET: {ticket_id}",
        f"TITLE: {ticket_title}",
        "",
        "BODY:",
        ticket_body.strip(),
        "",
        "RETRIEVED CODEBASE CONTEXT:",
    ]
    if not rag_hits:
        lines.append("  (no context retrieved — the repo may be empty or the query was off)")
    for i, h in enumerate(rag_hits, 1):
        meta = h.get("metadata") or {}
        snippet = (h.get("text") or meta.get("text") or "")[:800]
        lines.append(
            f"  [{i}] {meta.get('file')}:L{meta.get('start_line')}-{meta.get('end_line')}  "
            f"({meta.get('kind')} {meta.get('name')})"
        )
        for ln in snippet.splitlines()[:25]:
            lines.append(f"      {ln}")
        lines.append("")
    return "\n".join(lines)


def build_lead_agent() -> Agent:
    models = load_model_config()
    slug = models["engineering_lead"]["model"]
    return Agent(
        name="EngineeringLead",
        instructions=ENGINEERING_LEAD_INSTRUCTIONS,
        model=openrouter_model(slug),
        output_type=TaskPlan,
    )


async def plan_ticket(
    ticket_id: str,
    ticket_title: str,
    ticket_body: str,
    rag_hits: list[dict],
) -> TaskPlan:
    agent = build_lead_agent()
    user_input = build_input(ticket_id, ticket_title, ticket_body, rag_hits)
    result = await Runner.run(agent, input=user_input)
    return result.final_output
