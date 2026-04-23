"""DevForge worker entrypoint.

Day 2 scope: minimal smoke test. Configures the OpenAI-compatible client
to talk to OpenRouter, asks one agent to say hello, prints the result.

Day 5+ scope: full 4-agent crew orchestration (Lead -> Backend + Frontend -> QA).

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

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)

from agents import Agent, Runner, set_default_openai_client, set_tracing_disabled  # noqa: E402
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from backend.common import get_backend  # noqa: E402


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODELS_YAML = Path(__file__).resolve().parent / "models.yaml"

_openrouter_client: AsyncOpenAI | None = None


def load_model_config() -> dict:
    with open(MODELS_YAML) as f:
        return yaml.safe_load(f)


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
    set_tracing_disabled(True)
    return _openrouter_client


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
            "'DevForge Day 2 OK' and nothing else."
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


async def main() -> None:
    mode = os.environ.get("DEVFORGE_WORKER_MODE", "smoke")
    if mode == "smoke":
        await smoke_test()
    elif mode == "embed":
        await embed_smoke()
    elif mode == "attacker":
        await attacker_probe()
    elif mode == "all":
        await smoke_test()
        await embed_smoke()
    else:
        print(f"[error] unknown DEVFORGE_WORKER_MODE: {mode}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
