"""Modal deployment for the Technical Research Agent.

Deploy with::

    modal deploy modal_app.py

This creates a public HTTPS endpoint that runs the same pipeline as the local CLI.
The endpoint returns the rendered markdown brief plus run metadata as JSON.

Secrets to configure in the Modal dashboard (https://modal.com/secrets):
- ``anthropic-api-key`` with key ``ANTHROPIC_API_KEY`` — required
- ``langfuse-keys`` with ``LANGFUSE_PUBLIC_KEY`` + ``LANGFUSE_SECRET_KEY`` + ``LANGFUSE_HOST`` — optional
- ``mem0-key`` with ``MEM0_API_KEY`` — optional
- ``browserbase-keys`` with ``BROWSERBASE_API_KEY`` + ``BROWSERBASE_PROJECT_ID`` — optional

Listed optional secrets are pulled if present; the agent gracefully no-ops
when any of them are missing (see ``observability.py`` / ``memory.py`` /
``adapters/google_scholar.py``).
"""

from __future__ import annotations

import modal

app = modal.App("ai-research-agent")

# Build the runtime image directly from the repo's pyproject + lock.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "langgraph>=0.4.0",
        "anthropic>=0.40.0",
        "pydantic>=2.9",
        "httpx>=0.27",
        "arxiv>=2.1",
        "typer>=0.12",
        "python-dotenv>=1.0",
        "pypdf>=6.10.2",
        "langfuse>=4.5.0",
        "mem0ai>=1.0.0",
        "fastapi[standard]>=0.115.0",
    )
    .add_local_python_source("research_agent")
    .add_local_dir("prompts", "/root/prompts")
)

# Required: Anthropic API key. Configure in https://modal.com/secrets:
#   Name: anthropic-api-key
#   Key:  ANTHROPIC_API_KEY = sk-ant-...
SECRETS: list[modal.Secret] = [
    modal.Secret.from_name("anthropic-api-key"),
    # Uncomment the lines below for the optional integrations you've configured.
    # Each adapter no-ops gracefully when its env vars are missing, so it's safe
    # to deploy without them.
    #
    # modal.Secret.from_name("langfuse-keys"),     # LANGFUSE_PUBLIC_KEY + _SECRET_KEY + _HOST
    # modal.Secret.from_name("mem0-key"),          # MEM0_API_KEY
    # modal.Secret.from_name("browserbase-keys"),  # BROWSERBASE_API_KEY + _PROJECT_ID
]


@app.function(
    image=image,
    secrets=SECRETS,
    timeout=600,  # 10 minutes — generous for slow rate-limit retries
    cpu=1.0,
    memory=2048,
)
@modal.fastapi_endpoint(method="POST", docs=True)
def research(payload: dict) -> dict:
    """Run the research pipeline. POST JSON body ``{"query": "..."}``."""
    import asyncio
    import time

    from research_agent.config import load_settings
    from research_agent.graph import build_graph
    from research_agent.observability import flush as langfuse_flush
    from research_agent.render import brief_to_markdown

    query = (payload.get("query") or "").strip()
    if not query:
        return {"error": "missing 'query' field in JSON body"}

    load_settings()  # validate ANTHROPIC_API_KEY present
    state = {
        "query": query,
        "errors": [],
        "use_web": payload.get("use_web", True),
        "use_scholar": payload.get("use_scholar", False),
        "limit_per_source": payload.get("limit_per_source", 10),
        "top_n": payload.get("top_n", 10),
    }

    graph = build_graph()
    started = time.time()
    try:
        final = asyncio.run(graph.ainvoke(state))
    finally:
        langfuse_flush()
    elapsed = time.time() - started

    brief = final.get("brief")
    if brief is None:
        return {"error": "pipeline produced no brief", "errors": final.get("errors") or []}

    return {
        "query": query,
        "elapsed_sec": round(elapsed, 1),
        "n_candidates": len(final.get("candidates") or []),
        "n_selected": len(final.get("selected") or []),
        "n_facts": len(final.get("facts") or []),
        "n_findings": len(brief.key_findings),
        "n_citations": len(brief.citations),
        "errors": final.get("errors") or [],
        "brief_markdown": brief_to_markdown(brief),
        "brief": brief.model_dump(mode="json"),
    }


@app.function(image=image, secrets=SECRETS, timeout=900)
def eval_run() -> dict:
    """Run the eval suite remotely (callable from Python or `modal run`)."""
    import asyncio
    from dataclasses import asdict

    from research_agent.config import load_settings
    from research_agent.eval.runner import render_markdown, run_eval

    load_settings()
    report = asyncio.run(run_eval())
    return {
        "markdown": render_markdown(report),
        "report": {**asdict(report)},
    }
