"""``synthesize_node`` — assemble the final Brief from extracted facts via Sonnet."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from research_agent.llm import call_sonnet, extract_json_tag
from research_agent.memory import store_brief
from research_agent.models import Brief, Candidate, Citation, ExtractedFact
from research_agent.observability import observe
from research_agent.prompts import load_prompt
from research_agent.state import ResearchState

logger = logging.getLogger(__name__)


def _format_facts(facts: list[ExtractedFact], by_url: dict[str, Candidate]) -> str:
    lines: list[str] = []
    for i, f in enumerate(facts, start=1):
        url = str(f.candidate_url)
        c = by_url.get(url)
        title = c.title if c else url
        source = c.source if c else "?"
        quotes = " | ".join(f.quotes) if f.quotes else ""
        lines.append(
            f"[{i}] ({source}) {title}\n"
            f"     URL: {url}\n"
            f"     Thesis: {f.thesis}\n"
            f"     Methods: {', '.join(f.methods) if f.methods else '—'}\n"
            f"     Quotes: {quotes or '—'}"
        )
    return "\n\n".join(lines)


@observe(name="synthesize_node")
async def synthesize_node(state: ResearchState) -> dict:
    query = state["query"]
    facts = state.get("facts") or []
    selected = state.get("selected") or []
    by_url = {str(c.url): c for c in selected}

    if not facts:
        logger.warning("synthesize_node: no facts to work with")
        empty = Brief(
            query=query,
            executive_summary=(
                "No usable sources were found or read for this query. "
                "Try rephrasing the topic or running with --verbose to inspect errors."
            ),
        )
        return {"brief": empty}

    system = load_prompt("synthesize")
    user = (
        f"Query: {query}\n\n"
        f"Facts ({len(facts)}):\n\n{_format_facts(facts, by_url)}\n\n"
        f"Produce the Brief now."
    )

    raw = call_sonnet(system=system, user=user, max_tokens=4096, temperature=0.3)

    try:
        payload = extract_json_tag(raw)
    except Exception as exc:
        logger.error("synthesize_node JSON parse failed: %s", exc)
        return {
            "brief": Brief(
                query=query,
                executive_summary="The model did not return valid JSON. See logs.",
            )
        }

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
        except ValidationError as exc:
            logger.warning("citation validation failed: %s", exc)
            continue

    brief = Brief(
        query=query,
        executive_summary=payload.get("executive_summary", "").strip(),
        key_findings=[s for s in payload.get("key_findings", []) if isinstance(s, str)],
        comparison_matrix=[
            row for row in payload.get("comparison_matrix", []) if isinstance(row, dict)
        ],
        open_questions=[s for s in payload.get("open_questions", []) if isinstance(s, str)],
        citations=citations,
    )
    logger.info(
        "synthesize_node: %d findings, %d citations, matrix rows=%d",
        len(brief.key_findings),
        len(brief.citations),
        len(brief.comparison_matrix),
    )
    store_brief(query, brief)
    return {"brief": brief}
