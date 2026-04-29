"""GitHub repository search adapter — public REST endpoint, optional bearer token."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from research_agent.config import GITHUB_README_TRUNCATE, load_settings
from research_agent.models import Candidate

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.github.com/search/repositories"
_RAW_README_URL = "https://raw.githubusercontent.com/{full_name}/HEAD/README.md"


def _headers() -> dict[str, str]:
    settings = load_settings()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "research-agent/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


async def search(query: str, limit: int = 8) -> list[Candidate]:
    params: dict[str, Any] = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": limit,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(_SEARCH_URL, params=params, headers=_headers())
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:
        logger.warning("github search failed for %r: %s", query, exc)
        return []

    out: list[Candidate] = []
    for item in payload.get("items", []):
        out.append(
            Candidate(
                source="github",
                url=item["html_url"],
                title=item["full_name"],
                snippet=(item.get("description") or "").strip(),
                extra={
                    "stars": item.get("stargazers_count"),
                    "language": item.get("language"),
                    "updated_at": item.get("updated_at"),
                    "full_name": item["full_name"],
                },
            )
        )
    return out


async def fetch_readme(full_name: str) -> str:
    """Best-effort README fetch. Returns empty string on failure."""
    url = _RAW_README_URL.format(full_name=full_name)
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return ""
            return r.text[:GITHUB_README_TRUNCATE]
    except Exception as exc:
        logger.warning("github README fetch failed for %s: %s", full_name, exc)
        return ""
