"""``rank_node`` — Haiku reranks candidates and picks top N with diversity."""

from __future__ import annotations

import json
import logging

from research_agent.config import DEFAULT_TOP_N_SELECTED
from research_agent.llm import call_haiku, extract_json_tag
from research_agent.models import Candidate
from research_agent.observability import observe
from research_agent.prompts import load_prompt
from research_agent.state import ResearchState

logger = logging.getLogger(__name__)


def _format_candidates(candidates: list[Candidate]) -> str:
    lines: list[str] = []
    for i, c in enumerate(candidates):
        snippet = c.snippet[:300].replace("\n", " ")
        lines.append(f"[{i}] ({c.source}) {c.title}\n     {snippet}")
    return "\n".join(lines)


@observe(name="rank_node")
async def rank_node(state: ResearchState) -> dict:
    candidates = state.get("candidates") or []
    top_n = state.get("top_n", DEFAULT_TOP_N_SELECTED)

    if not candidates:
        return {"selected": []}

    if len(candidates) <= top_n:
        logger.info("rank_node: only %d candidates, skipping rerank", len(candidates))
        return {"selected": list(candidates)}

    system = load_prompt("rank")
    user = (
        f"Original query: {state['query']}\n\n"
        f"N = {top_n}\n\n"
        f"Candidates ({len(candidates)} total):\n{_format_candidates(candidates)}"
    )

    raw = call_haiku(system=system, user=user, max_tokens=1024, temperature=0.0)

    try:
        payload = extract_json_tag(raw)
        items = payload.get("selected", [])
        indices = [int(item["index"]) for item in items if "index" in item]
    except Exception as exc:
        logger.warning("rank_node parse failed (%s); falling back to top-%d order", exc, top_n)
        indices = list(range(min(top_n, len(candidates))))

    seen: set[int] = set()
    selected: list[Candidate] = []
    for i in indices:
        if 0 <= i < len(candidates) and i not in seen:
            seen.add(i)
            selected.append(candidates[i])
        if len(selected) >= top_n:
            break

    if not selected:
        selected = candidates[:top_n]

    logger.info("rank_node selected %d / %d", len(selected), len(candidates))
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("rank_node response: %s", json.dumps(raw)[:500])
    return {"selected": selected}
