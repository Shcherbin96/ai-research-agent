"""``plan_node`` — decompose the user query into 3-6 search subqueries via Sonnet."""

from __future__ import annotations

import logging

from research_agent.llm import call_sonnet, extract_json_tag
from research_agent.memory import recall as memory_recall
from research_agent.observability import observe
from research_agent.prompts import load_prompt
from research_agent.state import ResearchState

logger = logging.getLogger(__name__)


def _format_recalled(memories: list[dict]) -> str:
    if not memories:
        return ""
    lines = ["", "## Related past research (use as context, do not repeat verbatim):"]
    for i, m in enumerate(memories, start=1):
        excerpt = m["text"].strip().splitlines()[:6]
        lines.append(f"\n### Memory {i}")
        lines.extend(excerpt)
    return "\n".join(lines)


@observe(name="plan_node")
async def plan_node(state: ResearchState) -> dict:
    query = state["query"]
    memories = memory_recall(query, limit=3)
    if memories:
        logger.info("plan_node: recalled %d past memories", len(memories))

    system = load_prompt("plan")
    user = f"User query: {query}\n\nProduce 3–6 subqueries.{_format_recalled(memories)}"

    raw = call_sonnet(system=system, user=user, max_tokens=1024, temperature=0.3, node="plan")
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
