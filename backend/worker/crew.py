"""DevForge worker entrypoint.

Smoke test scope: minimal smoke test. Configures the OpenAI-compatible client
to talk to OpenRouter, asks one agent to say hello, prints the result.

Full agents scope: full 4-agent crew orchestration (Lead -> Backend + Frontend -> QA).

Runs locally (`uv run python -m backend.worker.crew`) or as a Fargate task. The
OpenRouter API key is read via backend.common.secrets so the same code works in
both modes.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)

from agents import Agent, Runner, set_default_openai_client, set_tracing_disabled  # noqa: E402
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from backend.common import get_backend  # noqa: E402
from backend.cost.tracker import install_cost_hook  # noqa: E402


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODELS_YAML = Path(__file__).resolve().parent / "models.yaml"

_openrouter_client: AsyncOpenAI | None = None


def load_model_config() -> dict:
    """Load per-agent model + fallback config.

    Precedence (highest first):
      1. DEVFORGE_MODEL_<AGENT_KEY>  (e.g. DEVFORGE_MODEL_ENGINEERING_LEAD)
      2. DEVFORGE_MODEL_DEFAULT      (overrides every unset agent)
      3. models.yaml on disk         (committed defaults)

    Same precedence applies to fallback chains via
    DEVFORGE_MODEL_<AGENT_KEY>_FALLBACK (comma-separated). Empty value clears
    the fallback chain.
    """
    with open(MODELS_YAML) as f:
        cfg = yaml.safe_load(f) or {}

    default_model = os.environ.get("DEVFORGE_MODEL_DEFAULT", "").strip()
    default_fallback_env = os.environ.get("DEVFORGE_MODEL_DEFAULT_FALLBACK")

    for agent_key in list(cfg.keys()):
        env_model = os.environ.get(f"DEVFORGE_MODEL_{agent_key.upper()}", "").strip()
        if env_model:
            cfg[agent_key]["model"] = env_model
        elif default_model:
            cfg[agent_key]["model"] = default_model

        env_fallback = os.environ.get(f"DEVFORGE_MODEL_{agent_key.upper()}_FALLBACK")
        chosen_fb = env_fallback if env_fallback is not None else default_fallback_env
        if chosen_fb is not None:
            cfg[agent_key]["fallback"] = [s.strip() for s in chosen_fb.split(",") if s.strip()]

    return cfg


def configure_openrouter() -> AsyncOpenAI:
    """Wire the Agents SDK to route chat completions through OpenRouter."""
    global _openrouter_client
    if _openrouter_client is not None:
        return _openrouter_client

    key = get_backend().secrets.get("openrouter-api-key")
    _openrouter_client = AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=key,
        default_headers={
            "HTTP-Referer": "https://devforge.app",
            "X-Title": "DevForge",
        },
    )
    set_default_openai_client(_openrouter_client, use_for_tracing=False)
    # Tracing: opt into LangFuse cloud when env vars are set, otherwise off.
    if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
        try:
            _enable_langfuse_tracing()
        except Exception as exc:  # pragma: no cover - never break agent on observability
            print(f"[trace] langfuse not enabled: {exc}", flush=True)
            set_tracing_disabled(True)
    else:
        set_tracing_disabled(True)
    install_cost_hook(_openrouter_client)
    return _openrouter_client


def _enable_langfuse_tracing() -> None:
    """Mirror Agents-SDK traces and spans to LangFuse cloud.

    Implementation: a `TracingExporter` that converts each Agents-SDK `Trace`
    object into a LangFuse trace, and each `Span` into a child span with the
    matching parent. Uses langfuse v4's generic OTel-style span API
    (`start_span` / `update`).

    No-op (and prints a friendly note) if `langfuse` isn't installed
    (`uv sync --extra obs`).
    """
    from agents.tracing import add_trace_processor
    from agents.tracing.processors import BatchTraceProcessor

    try:
        from langfuse import Langfuse  # type: ignore
    except ImportError:
        print("[trace] langfuse package not installed (uv sync --extra obs)", flush=True)
        set_tracing_disabled(True)
        return

    lf = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )

    class _LangfuseExporter:
        """Maps Agents-SDK Trace/Span objects into LangFuse traces + spans."""

        def export(self, items):  # type: ignore[no-untyped-def]
            # Group items by trace_id so we can build trace -> spans hierarchy
            # in one pass. Items in a single batch can be a mix of Trace + Span.
            from agents.tracing.spans import Span  # local import — lazy
            from agents.tracing.traces import Trace  # local import — lazy

            traces_by_id: dict[str, dict] = {}
            spans_by_trace: dict[str, list] = {}

            for it in items:
                data = it.export() if hasattr(it, "export") else {}
                if not data:
                    continue
                if isinstance(it, Trace):
                    traces_by_id[data.get("id") or data.get("trace_id") or ""] = data
                elif isinstance(it, Span):
                    tid = data.get("trace_id") or ""
                    spans_by_trace.setdefault(tid, []).append(data)

            for trace_id, trace_data in traces_by_id.items():
                try:
                    name = (
                        trace_data.get("workflow_name")
                        or trace_data.get("name")
                        or "agent_workflow"
                    )
                    # Forward the Agents-SDK trace_id to LangFuse so deep links
                    # from /jobs/[id] resolve. LangFuse expects 32-hex (OTel)
                    # without the "trace_" prefix.
                    lf_trace_id = (trace_id or "").removeprefix("trace_") or None
                    trace_ctx = {"trace_id": lf_trace_id} if lf_trace_id else None
                    with lf.start_as_current_observation(
                        trace_context=trace_ctx,
                        name=name, as_type="agent", metadata=trace_data,
                    ) as root:
                        for span_data in spans_by_trace.pop(trace_id, []):
                            _emit_child_span(root, span_data)
                except Exception as exc:  # pragma: no cover
                    print(f"[trace] export failed: {exc}", flush=True)

            # Orphan spans whose parent landed in a different batch — emit as
            # standalone observations so they're not lost. Forward their
            # parent trace_id so they nest under the right job.
            for orphan_tid, span_list in spans_by_trace.items():
                lf_orphan_tid = (orphan_tid or "").removeprefix("trace_") or None
                orphan_ctx = {"trace_id": lf_orphan_tid} if lf_orphan_tid else None
                for span_data in span_list:
                    try:
                        sd = span_data.get("span_data") or {}
                        span_name = sd.get("name") or sd.get("type") or "orphan_span"
                        with lf.start_as_current_observation(
                            trace_context=orphan_ctx,
                            name=span_name, as_type="span", metadata=span_data,
                        ):
                            pass
                    except Exception:
                        pass

            try:
                lf.flush()
            except Exception:
                pass

    def _emit_child_span(root, span_data: dict) -> None:
        """Emit one Agents-SDK Span as a child of `root`. Picks an `as_type`
        based on the span's `span_data.type`."""
        sd = span_data.get("span_data") or {}
        span_type = (sd.get("type") or "").lower()
        kind_map = {
            "generation": "generation",
            "response": "generation",
            "function": "tool",
            "tool": "tool",
            "agent": "agent",
            "guardrail": "guardrail",
            "handoff": "chain",
        }
        as_type = kind_map.get(span_type, "span")
        name = sd.get("name") or sd.get("type") or "span"

        with root.start_as_current_observation(
            name=name, as_type=as_type, metadata=span_data,
        ) as child:
            if span_data.get("error"):
                child.update(level="ERROR", status_message=str(span_data["error"]))

    add_trace_processor(BatchTraceProcessor(_LangfuseExporter()))
    print(f"[trace] langfuse tracing enabled -> "
          f"{os.environ.get('LANGFUSE_HOST', 'https://cloud.langfuse.com')}", flush=True)


def openrouter_model(slug: str) -> OpenAIChatCompletionsModel:
    client = configure_openrouter()
    return OpenAIChatCompletionsModel(model=slug, openai_client=client)


async def smoke_test() -> None:
    models = load_model_config()
    slug = models["engineering_lead"]["model"]
    print(f"[smoke] backend: {os.environ.get('DEVFORGE_BACKEND', 'local')}", flush=True)
    print(f"[smoke] using model: {slug}", flush=True)

    agent = Agent(
        name="SmokeAgent",
        instructions=(
            "You are a smoke test. Reply with exactly the phrase "
            "'DevForge Smoke Test OK' and nothing else."
        ),
        model=openrouter_model(slug),
    )
    result = await Runner.run(agent, input="run the smoke test")
    print(f"[smoke] response: {result.final_output}", flush=True)


async def embed_smoke() -> None:
    """Quick check that the embedder + vector store work for this backend."""
    b = get_backend()
    print(f"[embed] backend: {os.environ.get('DEVFORGE_BACKEND', 'local')}", flush=True)
    vec = b.embedder.embed("DevForge local smoke test")
    print(f"[embed] vector dims: {len(vec)}", flush=True)
    b.vectors.put(
        index="devforge-smoke",
        key="smoke-1",
        vector=vec,
        metadata={"text": "DevForge local smoke test", "kind": "smoke"},
    )
    hits = b.vectors.query(index="devforge-smoke", vector=vec, k=3)
    print(f"[embed] nearest: {hits[:1]}", flush=True)


async def attacker_probe() -> None:
    """Negative test — run in AWS mode inside a Fargate task with egress SG in place."""
    import httpx

    print("[probe] attempting outbound to http://attacker.com/ ...", flush=True)
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get("http://attacker.com/")
            print(f"[probe] UNEXPECTED: got HTTP {r.status_code}", flush=True)
            sys.exit(2)
    except Exception as exc:
        print(f"[probe] EXPECTED block: {type(exc).__name__}: {exc}", flush=True)


async def plan_mode() -> None:
    """Run the EngineeringLead agent against a ticket supplied via env vars.

    Required env:
      DEVFORGE_TICKET_ID, DEVFORGE_TICKET_TITLE, DEVFORGE_TICKET_BODY, DEVFORGE_TENANT_ID
    """
    from backend.ingest.index_tenant_repo import search_codebase
    from backend.worker.lead import plan_ticket

    tenant_id = int(os.environ.get("DEVFORGE_TENANT_ID", "1"))
    ticket_id = os.environ.get("DEVFORGE_TICKET_ID", "DEMO-1")
    ticket_title = os.environ.get("DEVFORGE_TICKET_TITLE", "Add /stats endpoint returning user count")
    ticket_body = os.environ.get(
        "DEVFORGE_TICKET_BODY",
        "Add a GET /stats endpoint that returns JSON {\"user_count\": N} where "
        "N is len(USERS). Add a test case in tests/test_main.py.",
    )

    print(f"[plan] backend: {os.environ.get('DEVFORGE_BACKEND', 'local')}", flush=True)
    print(f"[plan] tenant_id: {tenant_id}", flush=True)
    print(f"[plan] ticket: {ticket_id} {ticket_title!r}", flush=True)

    hits = search_codebase(tenant_id, f"{ticket_title}\n{ticket_body}", k=6)
    print(f"[plan] retrieved {len(hits)} codebase chunks", flush=True)

    plan = await plan_ticket(ticket_id, ticket_title, ticket_body, hits)
    print("\n=== TaskPlan ===")
    print(plan.model_dump_json(indent=2))


async def main() -> None:
    mode = os.environ.get("DEVFORGE_WORKER_MODE", "smoke")
    if mode == "smoke":
        await smoke_test()
    elif mode == "embed":
        await embed_smoke()
    elif mode == "attacker":
        await attacker_probe()
    elif mode == "plan":
        await plan_mode()
    elif mode == "all":
        await smoke_test()
        await embed_smoke()
    else:
        print(f"[error] unknown DEVFORGE_WORKER_MODE: {mode}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
