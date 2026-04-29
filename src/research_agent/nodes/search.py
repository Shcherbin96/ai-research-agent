"""``search_node`` — fan out subqueries across arXiv, GitHub, and Anthropic web_search."""

from __future__ import annotations

import asyncio
import logging

from research_agent.adapters import arxiv as arxiv_adapter
from research_agent.adapters import github as github_adapter
from research_agent.adapters import web_search as web_adapter
from research_agent.config import DEFAULT_LIMIT_PER_SOURCE
from research_agent.models import Candidate
from research_agent.state import ResearchState

logger = logging.getLogger(__name__)


async def search_node(state: ResearchState) -> dict:
    subqueries = state.get("subqueries") or [state["query"]]
    use_web = state.get("use_web", True)
    limit = state.get("limit_per_source", DEFAULT_LIMIT_PER_SOURCE)

    tasks = []
    for q in subqueries:
        tasks.append(arxiv_adapter.search(q, limit=limit))
        tasks.append(github_adapter.search(q, limit=max(4, limit // 2)))
        if use_web:
            tasks.append(web_adapter.search(q, limit=max(4, limit // 2)))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates: list[Candidate] = []
    errors: list[str] = list(state.get("errors") or [])
    for r in results:
        if isinstance(r, Exception):
            errors.append(f"adapter error: {r!r}")
            continue
        candidates.extend(r)

    deduped: dict[str, Candidate] = {}
    for c in candidates:
        key = str(c.url)
        if key not in deduped:
            deduped[key] = c

    capped = list(deduped.values())[:50]
    logger.info(
        "search_node: %d raw -> %d unique (capped %d), %d errors",
        len(candidates),
        len(deduped),
        len(capped),
        len(errors) - len(state.get("errors") or []),
    )
    return {"candidates": capped, "errors": errors}
