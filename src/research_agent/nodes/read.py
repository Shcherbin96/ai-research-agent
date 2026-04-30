"""``read_node`` — fetch source bodies and extract structured facts via Sonnet."""

from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError

from research_agent.adapters import arxiv as arxiv_adapter
from research_agent.adapters import github as github_adapter
from research_agent.config import READ_NODE_CONCURRENCY
from research_agent.llm import call_sonnet, extract_json_tag
from research_agent.models import Candidate, ExtractedFact
from research_agent.observability import observe
from research_agent.prompts import load_prompt
from research_agent.state import ResearchState

logger = logging.getLogger(__name__)


async def _body_for(c: Candidate) -> str:
    """Best-effort body for fact extraction.

    - arXiv: download PDF, extract text via pypdf; fall back to abstract.
    - GitHub: fetch raw README (HEAD); fall back to repo description.
    - web: rely on the search snippet (web_search returns ~500 chars).
    """
    if c.source == "arxiv":
        pdf_url = c.extra.get("pdf_url") if isinstance(c.extra, dict) else None
        return await arxiv_adapter.fetch_paper_text(pdf_url, fallback_abstract=c.snippet)
    if c.source == "github":
        full_name = c.extra.get("full_name") if isinstance(c.extra, dict) else None
        readme = ""
        if full_name:
            readme = await github_adapter.fetch_readme(full_name)
        return readme or c.snippet
    return c.snippet  # web


async def _extract_one(
    c: Candidate, system: str, semaphore: asyncio.Semaphore
) -> ExtractedFact | None:
    body = await _body_for(c)
    if not body.strip():
        logger.info("read_node: empty body for %s, skipping", c.url)
        return None

    user = (
        f"Title: {c.title}\n"
        f"URL: {c.url}\n"
        f"Source type: {c.source}\n\n"
        f"Body:\n{body}"
    )
    async with semaphore:
        raw = await asyncio.to_thread(
            call_sonnet, system=system, user=user, max_tokens=1024, temperature=0.1
        )

    try:
        payload = extract_json_tag(raw)
    except Exception as exc:
        logger.warning("read_node JSON parse failed for %s: %s", c.url, exc)
        return None

    try:
        return ExtractedFact(
            candidate_url=str(c.url),
            thesis=payload.get("thesis", "").strip(),
            methods=[m for m in payload.get("methods", []) if isinstance(m, str)],
            quotes=[q for q in payload.get("quotes", []) if isinstance(q, str)],
        )
    except ValidationError as exc:
        logger.warning("read_node validation failed for %s: %s", c.url, exc)
        return None


@observe(name="read_node")
async def read_node(state: ResearchState) -> dict:
    selected = state.get("selected") or []
    if not selected:
        return {"facts": []}

    system = load_prompt("read")
    semaphore = asyncio.Semaphore(READ_NODE_CONCURRENCY)
    results = await asyncio.gather(
        *[_extract_one(c, system, semaphore) for c in selected],
        return_exceptions=True,
    )

    facts: list[ExtractedFact] = []
    errors: list[str] = list(state.get("errors") or [])
    n_exceptions = 0
    for c, r in zip(selected, results, strict=False):
        if isinstance(r, Exception):
            n_exceptions += 1
            errors.append(f"read error for {c.url}: {r!r}")
            logger.warning("read_node: %s failed: %r", c.url, r)
            continue
        if r is not None and r.thesis:
            facts.append(r)

    logger.info(
        "read_node extracted %d / %d facts (%d exceptions)",
        len(facts),
        len(selected),
        n_exceptions,
    )
    return {"facts": facts, "errors": errors}
