"""Modal deployment for the Technical Research Agent.

Deploy with::

    modal deploy modal_app.py

This creates a public HTTPS endpoint that serves both:
- ``GET /`` — interactive web UI (single-page app, Tailwind + Alpine.js)
- ``POST /api/research`` — JSON API: `{"query": "..."}` returns the rendered brief
- ``POST /`` — same API, kept for the curl example in the README

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

# Persistent KV store for shareable briefs. Survives container restarts.
briefs_store = modal.Dict.from_name("ai-research-agent-briefs", create_if_missing=True)

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
    .add_local_dir("web", "/root/web")
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


def _run_pipeline(payload: dict) -> dict:
    """Shared logic for both POST routes."""
    import asyncio
    import time

    from research_agent.config import load_settings
    from research_agent.graph import build_graph
    from research_agent.llm import get_run_usage, reset_run_usage
    from research_agent.observability import flush as langfuse_flush
    from research_agent.render import brief_to_markdown

    query = (payload.get("query") or "").strip()
    if not query:
        return {"error": "missing 'query' field in JSON body"}

    load_settings()
    state = {
        "query": query,
        "errors": [],
        "use_web": payload.get("use_web", True),
        "use_scholar": payload.get("use_scholar", False),
        "limit_per_source": payload.get("limit_per_source", 10),
        "top_n": payload.get("top_n", 10),
    }

    graph = build_graph()
    reset_run_usage()
    started = time.time()
    try:
        final = asyncio.run(graph.ainvoke(state))
    finally:
        langfuse_flush()
    elapsed = time.time() - started
    usage = get_run_usage()

    brief = final.get("brief")
    if brief is None:
        return {
            "error": "pipeline produced no brief",
            "errors": final.get("errors") or [],
            "cost_usd": round(usage["total_cost_usd"], 4),
        }

    # Cost breakdown by node
    by_node: dict[str, dict[str, float | int]] = {}
    cache_read_tokens = 0
    cache_creation_tokens = 0
    for c in usage["calls"]:
        n = c.get("node") or "?"
        b = by_node.setdefault(n, {"cost_usd": 0.0, "calls": 0})
        b["cost_usd"] += c["cost_usd"]["total"]
        b["calls"] += 1
        cache_read_tokens += c["usage"].get("cache_read", 0)
        cache_creation_tokens += c["usage"].get("cache_creation", 0)

    # Persist for shareable link, but only if the brief has actual findings —
    # no point sharing an empty rate-limited result.
    import secrets as _secrets
    import time as _time
    brief_id = None
    if len(brief.key_findings) > 0:
        brief_id = _secrets.token_urlsafe(8)
        try:
            briefs_store[brief_id] = {
                "brief": brief.model_dump(mode="json"),
                "brief_markdown": brief_to_markdown(brief),
                "query": query,
                "elapsed_sec": round(elapsed, 1),
                "saved_at": _time.time(),
            }
        except Exception:
            brief_id = None

    return {
        "query": query,
        "brief_id": brief_id,
        "elapsed_sec": round(elapsed, 1),
        "n_candidates": len(final.get("candidates") or []),
        "n_selected": len(final.get("selected") or []),
        "n_facts": len(final.get("facts") or []),
        "n_findings": len(brief.key_findings),
        "n_citations": len(brief.citations),
        "errors": final.get("errors") or [],
        "cost_usd": round(usage["total_cost_usd"], 4),
        "cost_by_node": {
            n: {"cost_usd": round(d["cost_usd"], 4), "calls": d["calls"]}
            for n, d in by_node.items()
        },
        "cache_tokens": {
            "read": cache_read_tokens,
            "creation": cache_creation_tokens,
        },
        "brief_markdown": brief_to_markdown(brief),
        "brief": brief.model_dump(mode="json"),
    }


@app.function(
    image=image,
    secrets=SECRETS,
    timeout=600,  # 10 minutes — generous for slow rate-limit retries
    cpu=1.0,
    memory=2048,
)
@modal.asgi_app()
def research():
    """Web UI + JSON API + SSE streaming endpoint in one ASGI app."""
    import json as _json
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

    fa = FastAPI(title="Technical Research Agent", docs_url="/docs")

    # Cached HTML (read once at cold start).
    html_path = Path("/root/web/index.html")
    index_html = html_path.read_text(encoding="utf-8") if html_path.is_file() else (
        "<h1>UI not bundled</h1>"
    )

    @fa.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(index_html)

    @fa.get("/brief/{brief_id}", response_class=HTMLResponse)
    def shared_brief(brief_id: str) -> HTMLResponse:
        """Render a previously-saved brief by id, in the same UI shell."""
        try:
            saved = briefs_store[brief_id]
        except (KeyError, Exception):
            return HTMLResponse(
                "<h1>Brief not found</h1><p>This share link has expired or never existed.</p>",
                status_code=404,
            )
        # Inject the saved brief as a JS global so the page can render it on load.
        injected = (
            "<script>window.__SHARED_BRIEF__ = "
            + _json.dumps(saved)
            + ";</script>"
        )
        # Insert just before </head> so the script runs before Alpine init.
        if "</head>" in index_html:
            page = index_html.replace("</head>", injected + "</head>")
        else:
            page = injected + index_html
        return HTMLResponse(page)

    @fa.get("/api/brief/{brief_id}")
    def api_get_brief(brief_id: str) -> JSONResponse:
        try:
            saved = briefs_store[brief_id]
        except (KeyError, Exception):
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(saved)

    @fa.post("/api/research")
    def api_research(payload: dict) -> JSONResponse:
        return JSONResponse(_run_pipeline(payload))

    @fa.post("/api/research/stream")
    async def api_research_stream(payload: dict) -> StreamingResponse:
        """SSE endpoint. Emits ``stage`` / ``chunk`` / ``verify`` / ``result`` events."""
        from research_agent.config import load_settings
        from research_agent.streaming import stream_pipeline

        query = (payload.get("query") or "").strip()
        if not query:
            async def _err_stream():
                yield f"event: error\ndata: {_json.dumps({'message': 'missing query'})}\n\n"
            return StreamingResponse(_err_stream(), media_type="text/event-stream")

        load_settings()
        state = {
            "query": query,
            "errors": [],
            "use_web": payload.get("use_web", True),
            "use_scholar": payload.get("use_scholar", False),
            "limit_per_source": payload.get("limit_per_source", 10),
            "top_n": payload.get("top_n", 10),
        }

        async def event_stream():
            import secrets as _secrets
            import time as _time
            try:
                async for ev in stream_pipeline(state):
                    # On the final result event, persist the brief and inject brief_id —
                    # but only if it has real findings (don't share rate-limited empties).
                    if (
                        ev.get("type") == "result"
                        and ev.get("brief")
                        and ev.get("n_findings", 0) > 0
                    ):
                        brief_id = _secrets.token_urlsafe(8)
                        try:
                            briefs_store[brief_id] = {
                                "brief": ev["brief"],
                                "brief_markdown": ev.get("brief_markdown", ""),
                                "query": ev.get("query", ""),
                                "elapsed_sec": ev.get("elapsed_sec"),
                                "saved_at": _time.time(),
                            }
                            ev["brief_id"] = brief_id
                        except Exception:
                            pass
                    et = ev.get("type", "message")
                    yield f"event: {et}\ndata: {_json.dumps(ev)}\n\n"
            except Exception as exc:
                yield (
                    "event: error\ndata: "
                    + _json.dumps({"message": repr(exc)})
                    + "\n\n"
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Backward-compat: the README curl example still hits POST /.
    @fa.post("/")
    def root_post(payload: dict) -> JSONResponse:
        return JSONResponse(_run_pipeline(payload))

    return fa


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
