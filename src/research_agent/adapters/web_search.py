"""Web search adapter — Anthropic server-side ``web_search`` tool.

Anthropic runs the search server-side; we receive ``web_search_tool_result`` blocks
inside the assistant turn. ``llm.call_with_web_search`` does the API plumbing.
"""

from __future__ import annotations

import asyncio
import logging

from research_agent.llm import call_with_web_search
from research_agent.models import Candidate

logger = logging.getLogger(__name__)


async def search(query: str, limit: int = 8) -> list[Candidate]:
    try:
        items = await asyncio.to_thread(call_with_web_search, query=query, max_uses=2)
    except Exception as exc:
        logger.warning("web_search failed for %r: %s", query, exc)
        return []

    out: list[Candidate] = []
    for item in items[:limit]:
        try:
            out.append(
                Candidate(
                    source="web",
                    url=item["url"],
                    title=item.get("title") or item["url"],
                    snippet=item.get("snippet", ""),
                    extra={"page_age": item.get("page_age")},
                )
            )
        except Exception as exc:
            logger.warning("skipping malformed web result %r: %s", item, exc)
            continue
    return out
