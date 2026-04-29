"""Google Scholar adapter — uses Browserbase + Playwright (no public Scholar API).

Opt-in via ``BROWSERBASE_API_KEY`` and ``BROWSERBASE_PROJECT_ID`` env vars. Without
them, ``search`` returns ``[]`` and the rest of the pipeline runs untouched.

Scholar's HTML is stable but heavily anti-bot. Browserbase provides residential
proxies + CAPTCHA solving when ``solve_captchas=True``. Each call creates a fresh
session — there's no session reuse in MVP because Browserbase sessions cost real
money and we don't want to leak them across queries.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from research_agent.models import Candidate

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return bool(
        os.environ.get("BROWSERBASE_API_KEY") and os.environ.get("BROWSERBASE_PROJECT_ID")
    )


def _parse_year(text: str) -> int | None:
    m = re.search(r"\b(19|20|21)\d{2}\b", text)
    return int(m.group(0)) if m else None


def _scrape_sync(query: str, limit: int) -> list[Candidate]:
    """Synchronous Browserbase + Playwright scrape. Runs in a thread pool."""
    from browserbase import Browserbase
    from playwright.sync_api import sync_playwright

    api_key = os.environ["BROWSERBASE_API_KEY"]
    project_id = os.environ["BROWSERBASE_PROJECT_ID"]
    bb = Browserbase(api_key=api_key)

    session = bb.sessions.create(
        project_id=project_id,
        browser_settings={
            "solve_captchas": True,
            "block_ads": True,
        },
    )

    candidates: list[Candidate] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(session.connect_url)
            try:
                context = browser.contexts[0]
                page = context.pages[0]
                page.set_default_timeout(20000)
                page.goto(
                    f"https://scholar.google.com/scholar?q={query}", wait_until="domcontentloaded"
                )

                results = page.locator(".gs_ri").all()[:limit]
                for r in results:
                    try:
                        title_el = r.locator(".gs_rt a").first
                        title = title_el.text_content() or ""
                        url = title_el.get_attribute("href") or ""
                        snippet = (r.locator(".gs_rs").first.text_content() or "")[:600]
                        meta = r.locator(".gs_a").first.text_content() or ""
                    except Exception as exc:
                        logger.debug("scholar result parse failed: %s", exc)
                        continue
                    if not url or not title.strip():
                        continue
                    year = _parse_year(meta)
                    candidates.append(
                        Candidate(
                            source="web",  # Scholar results live in the same namespace as web
                            url=url,
                            title=title.strip(),
                            snippet=(snippet + ("\n" + meta if meta else "")).strip(),
                            extra={"scholar_meta": meta.strip(), "year": year},
                        )
                    )
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("scholar scrape failed for %r: %s", query, exc)
        return []

    return candidates


async def search(query: str, limit: int = 8) -> list[Candidate]:
    if not is_enabled():
        return []
    try:
        return await asyncio.to_thread(_scrape_sync, query, limit)
    except Exception as exc:
        logger.warning("scholar adapter failed: %s", exc)
        return []
