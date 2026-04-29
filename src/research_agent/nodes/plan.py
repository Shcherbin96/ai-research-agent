"""``plan_node`` — decompose the user query into 3-6 search subqueries via Sonnet."""

from __future__ import annotations

import logging

from research_agent.llm import call_sonnet, extract_json_tag
from research_agent.prompts import load_prompt
from research_agent.state import ResearchState

logger = logging.getLogger(__name__)


async def plan_node(state: ResearchState) -> dict:
    query = state["query"]
    system = load_prompt("plan")
    user = f"User query: {query}\n\nProduce 3–6 subqueries."

    raw = call_sonnet(system=system, user=user, max_tokens=1024, temperature=0.3)
    try:
        payload = extract_json_tag(raw)
        subqueries = [s.strip() for s in payload.get("subqueries", []) if isinstance(s, str)]
    except Exception as exc:
        logger.warning("plan_node JSON parse failed: %s", exc)
        subqueries = [query]

    if not subqueries:
        subqueries = [query]

    subqueries = subqueries[:6]
    logger.info("plan_node produced %d subqueries", len(subqueries))
    return {"subqueries": subqueries}
