"""Per-job OpenRouter cost tracking + cap enforcement.

OpenRouter reports `usage.cost` (USD) on every response. This tracker hooks
the OpenAI-compatible client's `.chat.completions.create` to accumulate per-
job spend and raise `CostCapExceeded` when the job cap is crossed.

Usage (wired in crew.py):
    from backend.cost.tracker import install_cost_hook, cap_for_job, start_job, end_job
    install_cost_hook(openrouter_client)
    start_job(job_id=..., cap_usd=float(os.environ.get("DEVFORGE_JOB_COST_CAP_USD", "2.0")))
    # ... run agents ...
    totals = end_job()
    # persist totals to job_events / jobs.final_cost_usd
"""
from __future__ import annotations

import contextvars
import os
from dataclasses import dataclass, field

from openai import AsyncOpenAI


# Per-asyncio-task cost context. An orchestrator runs one job at a time within
# its task, so we use a ContextVar to avoid leaking across concurrent calls.
@dataclass
class _JobCost:
    job_id: int | None = None
    cap_usd: float = 0.0
    spent_usd: float = 0.0
    by_model: dict[str, float] = field(default_factory=dict)
    calls: int = 0


_CTX: contextvars.ContextVar[_JobCost | None] = contextvars.ContextVar("devforge_job_cost", default=None)


class CostCapExceeded(RuntimeError):
    pass


def start_job(job_id: int, cap_usd: float = 2.0) -> _JobCost:
    state = _JobCost(job_id=job_id, cap_usd=cap_usd)
    _CTX.set(state)
    return state


def end_job() -> _JobCost | None:
    state = _CTX.get()
    _CTX.set(None)
    return state


def current() -> _JobCost | None:
    return _CTX.get()


def install_cost_hook(client: AsyncOpenAI) -> None:
    """Wrap client.chat.completions.create so we record usage.cost on every call."""
    if getattr(client, "_devforge_cost_hooked", False):
        return
    client._devforge_cost_hooked = True  # type: ignore[attr-defined]
    original = client.chat.completions.create

    async def _create(*args, **kwargs):
        resp = await original(*args, **kwargs)
        state = _CTX.get()
        if state is not None:
            # OpenRouter exposes usage.cost (float USD). Some providers omit it.
            usage = getattr(resp, "usage", None)
            cost = 0.0
            if usage is not None:
                cost = float(getattr(usage, "cost", 0.0) or 0.0)
                if not cost:
                    # Some providers put it inside model_extra / extra_body.
                    extra = getattr(resp, "model_extra", {}) or {}
                    cost = float((extra.get("cost") or 0.0))
            model = str(getattr(resp, "model", "unknown"))
            state.spent_usd += cost
            state.by_model[model] = state.by_model.get(model, 0.0) + cost
            state.calls += 1
            if state.cap_usd > 0 and state.spent_usd > state.cap_usd:
                raise CostCapExceeded(
                    f"job {state.job_id} cost cap hit: "
                    f"${state.spent_usd:.4f} > ${state.cap_usd:.2f}"
                )
        return resp

    client.chat.completions.create = _create  # type: ignore[assignment]


def default_cap() -> float:
    try:
        return float(os.environ.get("DEVFORGE_JOB_COST_CAP_USD", "2.0"))
    except ValueError:
        return 2.0
