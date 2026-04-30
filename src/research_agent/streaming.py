"""Streaming orchestrator for the SSE endpoint.

Calls the same node functions as the LangGraph pipeline, but interleaved with
event emissions so the client can render real-time progress. The synthesize
stage uses Anthropic's streaming API so brief text appears as it's generated.

Events emitted (each is a dict that the SSE endpoint serialises to JSON):

- ``{"type": "stage", "node": "plan", "status": "running"}`` — node started
- ``{"type": "stage", "node": "plan", "status": "done", "n_subqueries": 6}`` — node done + counts
- ``{"type": "chunk", "text": "..."}`` — synthesize text chunk (streaming)
- ``{"type": "verify", "support_rate": 0.83, "retry": false}`` — verifier result
- ``{"type": "result", ...}`` — final structured result (same shape as POST endpoint)
- ``{"type": "error", "message": "..."}`` — fatal error
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from pydantic import ValidationError

from research_agent.graph import MAX_SYNTHESIZE_ATTEMPTS, VERIFY_SUPPORT_THRESHOLD
from research_agent.llm import (
    extract_json_tag,
    get_run_usage,
    reset_run_usage,
    stream_sonnet,
)
from research_agent.memory import store_brief
from research_agent.models import Brief, Citation
from research_agent.nodes.plan import plan_node
from research_agent.nodes.rank import rank_node
from research_agent.nodes.read import read_node
from research_agent.nodes.search import search_node
from research_agent.nodes.synthesize import _format_facts
from research_agent.nodes.verify import verify_node
from research_agent.prompts import load_prompt
from research_agent.render import brief_to_markdown
from research_agent.state import ResearchState

logger = logging.getLogger(__name__)


def _build_brief_from_payload(payload: dict, query: str, facts: list, by_url: dict) -> Brief:
    citations_in: list[dict] = payload.get("citations", []) or []
    citations: list[Citation] = []
    for entry in citations_in:
        try:
            idx = int(entry["index"])
        except (KeyError, TypeError, ValueError):
            continue
        url = entry.get("candidate_url")
        title = entry.get("title")
        if not url and 1 <= idx <= len(facts):
            fact = facts[idx - 1]
            url = str(fact.candidate_url)
            title = title or (by_url[url].title if url in by_url else url)
        if not url:
            continue
        try:
            citations.append(
                Citation(
                    index=idx,
                    candidate_url=url,
                    title=title or url,
                    quote=entry.get("quote"),
                )
            )
        except ValidationError:
            continue

    return Brief(
        query=query,
        executive_summary=payload.get("executive_summary", "").strip(),
        key_findings=[s for s in payload.get("key_findings", []) if isinstance(s, str)],
        comparison_matrix=[
            row for row in payload.get("comparison_matrix", []) if isinstance(row, dict)
        ],
        open_questions=[s for s in payload.get("open_questions", []) if isinstance(s, str)],
        citations=citations,
    )


async def _stream_synthesize(state: ResearchState) -> AsyncIterator[dict]:
    """Run synthesize step with text streaming. Yields chunk events + a final
    ``{"type": "synthesize_done", "brief": Brief}`` event when done."""
    query = state["query"]
    facts = state.get("facts") or []
    selected = state.get("selected") or []
    by_url = {str(c.url): c for c in selected}
    feedback = state.get("verify_feedback", "")
    attempt = state.get("synthesize_attempts", 0)

    if not facts:
        empty = Brief(
            query=query,
            executive_summary=(
                "No usable sources were found or read for this query."
            ),
        )
        yield {"type": "synthesize_done", "brief": empty}
        return

    system = load_prompt("synthesize")
    user_parts = [
        f"Query: {query}",
        "",
        f"Facts ({len(facts)}):",
        "",
        _format_facts(facts, by_url),
    ]
    if feedback and attempt > 0:
        user_parts.extend(["", "## Verifier feedback from previous attempt", feedback])
    user_parts.extend(["", "Produce the Brief now."])
    user = "\n".join(user_parts)

    # Stream chunks from Sonnet. The streaming API is synchronous; run it in
    # a thread and bridge to async via a queue.
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()
    full_text: list[str] = []

    def producer() -> None:
        try:
            for chunk in stream_sonnet(
                system=system, user=user, max_tokens=4096,
                temperature=0.3, node="synthesize",
            ):
                full_text.append(chunk)
                queue.put_nowait(chunk)
        except Exception as exc:
            queue.put_nowait(("__error__", repr(exc)))
        finally:
            queue.put_nowait(SENTINEL)

    task = asyncio.create_task(asyncio.to_thread(producer))

    while True:
        item = await queue.get()
        if item is SENTINEL:
            break
        if isinstance(item, tuple) and item and item[0] == "__error__":
            yield {"type": "error", "message": item[1]}
            await task
            return
        yield {"type": "chunk", "text": item}

    await task

    raw = "".join(full_text)
    try:
        payload = extract_json_tag(raw)
    except Exception as exc:
        logger.warning("stream_synthesize JSON parse failed: %s", exc)
        empty = Brief(
            query=query,
            executive_summary="The model did not return valid JSON.",
        )
        yield {"type": "synthesize_done", "brief": empty}
        return

    brief = _build_brief_from_payload(payload, query, facts, by_url)
    yield {"type": "synthesize_done", "brief": brief}


async def stream_pipeline(state: ResearchState) -> AsyncIterator[dict]:
    """Run the full pipeline, emitting events at each stage boundary."""
    started = time.time()
    reset_run_usage()

    # Plan
    yield {"type": "stage", "node": "plan", "status": "running"}
    state.update(await plan_node(state))
    yield {
        "type": "stage", "node": "plan", "status": "done",
        "n_subqueries": len(state.get("subqueries") or []),
    }

    # Search
    yield {"type": "stage", "node": "search", "status": "running"}
    state.update(await search_node(state))
    yield {
        "type": "stage", "node": "search", "status": "done",
        "n_candidates": len(state.get("candidates") or []),
    }

    # Rank
    yield {"type": "stage", "node": "rank", "status": "running"}
    state.update(await rank_node(state))
    yield {
        "type": "stage", "node": "rank", "status": "done",
        "n_selected": len(state.get("selected") or []),
    }

    # Read
    yield {"type": "stage", "node": "read", "status": "running"}
    state.update(await read_node(state))
    yield {
        "type": "stage", "node": "read", "status": "done",
        "n_facts": len(state.get("facts") or []),
    }

    # Synthesize + verify, with up to MAX_SYNTHESIZE_ATTEMPTS attempts.
    brief: Brief | None = None
    while True:
        attempt = state.get("synthesize_attempts", 0)
        yield {
            "type": "stage", "node": "synthesize", "status": "running",
            "attempt": attempt + 1,
        }
        async for ev in _stream_synthesize(state):
            if ev["type"] == "synthesize_done":
                brief = ev["brief"]
                state["brief"] = brief
                state["synthesize_attempts"] = attempt + 1
            else:
                yield ev
        yield {
            "type": "stage", "node": "synthesize", "status": "done",
            "attempt": attempt + 1,
            "n_findings": len(brief.key_findings) if brief else 0,
        }

        # Verify
        yield {"type": "stage", "node": "verify", "status": "running"}
        state.update(await verify_node(state))
        rate = state.get("verify_support_rate", 1.0)
        attempts = state.get("synthesize_attempts", 0)
        retry = rate < VERIFY_SUPPORT_THRESHOLD and attempts < MAX_SYNTHESIZE_ATTEMPTS
        yield {
            "type": "verify",
            "support_rate": round(rate, 3),
            "retry": retry,
            "attempts": attempts,
        }
        if not retry:
            break

    if brief is not None:
        try:
            store_brief(state["query"], brief)
        except Exception:
            pass

    elapsed = time.time() - started
    usage = get_run_usage()

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

    if brief is None:
        yield {
            "type": "result",
            "error": "pipeline produced no brief",
            "errors": state.get("errors") or [],
            "elapsed_sec": round(elapsed, 1),
            "cost_usd": round(usage["total_cost_usd"], 4),
        }
        return

    yield {
        "type": "result",
        "query": state["query"],
        "elapsed_sec": round(elapsed, 1),
        "n_candidates": len(state.get("candidates") or []),
        "n_selected": len(state.get("selected") or []),
        "n_facts": len(state.get("facts") or []),
        "n_findings": len(brief.key_findings),
        "n_citations": len(brief.citations),
        "errors": state.get("errors") or [],
        "cost_usd": round(usage["total_cost_usd"], 4),
        "cost_by_node": {
            n: {"cost_usd": round(d["cost_usd"], 4), "calls": d["calls"]}
            for n, d in by_node.items()
        },
        "cache_tokens": {
            "read": cache_read_tokens, "creation": cache_creation_tokens,
        },
        "verify_support_rate": round(state.get("verify_support_rate", 1.0), 3),
        "synthesize_attempts": state.get("synthesize_attempts", 0),
        "brief_markdown": brief_to_markdown(brief),
        "brief": brief.model_dump(mode="json"),
    }
