"""arXiv search adapter — uses the public API via the ``arxiv`` library, no key needed.

For ``read_node`` we additionally fetch the paper PDF and extract its plain text via
``pypdf`` (truncated to a configurable budget). Falls back to the abstract if the
PDF download or parse fails.
"""

from __future__ import annotations

import asyncio
import io
import logging

import arxiv
import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from research_agent.config import ARXIV_PDF_TRUNCATE
from research_agent.models import Candidate

logger = logging.getLogger(__name__)


def _search_sync(query: str, limit: int) -> list[Candidate]:
    # arXiv rate-limits aggressively, especially from cloud IPs (Modal). Use a
    # generous delay + extra retries so a 429/503 doesn't kill the adapter.
    client = arxiv.Client(page_size=limit, delay_seconds=5.0, num_retries=5)
    search = arxiv.Search(
        query=query,
        max_results=limit,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    out: list[Candidate] = []
    for result in client.results(search):
        out.append(
            Candidate(
                source="arxiv",
                url=result.entry_id,
                title=result.title.strip(),
                snippet=result.summary.strip(),
                authors=[a.name for a in result.authors],
                published=result.published.date() if result.published else None,
                extra={
                    "arxiv_id": result.get_short_id(),
                    "primary_category": result.primary_category,
                    "pdf_url": result.pdf_url,
                },
            )
        )
    return out


# arXiv allows ~1 request per 3-5s per source IP. Across many parallel
# subqueries from search_node we'd hit 429 immediately, so serialize at the
# adapter boundary.
_ARXIV_SEMAPHORE: asyncio.Semaphore | None = None


def _get_arxiv_semaphore() -> asyncio.Semaphore:
    global _ARXIV_SEMAPHORE
    if _ARXIV_SEMAPHORE is None:
        _ARXIV_SEMAPHORE = asyncio.Semaphore(1)
    return _ARXIV_SEMAPHORE


async def search(query: str, limit: int = 10) -> list[Candidate]:
    sem = _get_arxiv_semaphore()
    async with sem:
        try:
            return await asyncio.to_thread(_search_sync, query, limit)
        except Exception as exc:
            logger.warning("arxiv search failed for %r: %s", query, exc)
            return []


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as exc:
            logger.debug("pdf page extract failed: %s", exc)
            continue
    return "\n".join(parts)


async def fetch_paper_text(pdf_url: str | None, fallback_abstract: str) -> str:
    """Best-effort PDF fetch + text extraction. Returns abstract on any failure."""
    if not pdf_url:
        return fallback_abstract
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(pdf_url, headers={"User-Agent": "research-agent/0.1"})
            if r.status_code != 200:
                logger.info("arxiv PDF %s returned %s, falling back", pdf_url, r.status_code)
                return fallback_abstract
            pdf_bytes = r.content
    except Exception as exc:
        logger.warning("arxiv PDF download failed for %s: %s", pdf_url, exc)
        return fallback_abstract

    try:
        text = await asyncio.to_thread(_extract_pdf_text, pdf_bytes)
    except (PdfReadError, Exception) as exc:
        logger.warning("arxiv PDF parse failed for %s: %s", pdf_url, exc)
        return fallback_abstract

    text = text.strip()
    if not text:
        return fallback_abstract
    return text[:ARXIV_PDF_TRUNCATE]
