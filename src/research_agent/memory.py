"""Optional Mem0 long-term memory.

If ``MEM0_API_KEY`` is set, completed briefs are stored as memories tagged with
the original query and citation URLs. When a new query arrives, ``recall`` returns
the top-K past memories most semantically similar to it, and ``plan_node`` injects
them as warm context for query decomposition.

If the key is missing, every function is a no-op and the agent runs unchanged.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from research_agent.models import Brief

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "research-agent"

_client: Any | None = None
_enabled: bool | None = None


def _resolve_enabled() -> bool:
    global _enabled
    if _enabled is not None:
        return _enabled
    has_key = bool(os.environ.get("MEM0_API_KEY"))
    _enabled = has_key
    if has_key:
        logger.info("Mem0 long-term memory enabled")
    else:
        logger.debug("MEM0_API_KEY not set — long-term memory disabled")
    return has_key


def is_enabled() -> bool:
    return _resolve_enabled()


def _get_client() -> Any | None:
    global _client
    if not _resolve_enabled():
        return None
    if _client is None:
        try:
            from mem0 import MemoryClient

            _client = MemoryClient()
        except Exception as exc:
            logger.warning("Mem0 init failed: %s", exc)
            _client = None
            return None
    return _client


def _user_id() -> str:
    return os.environ.get("MEM0_USER_ID", DEFAULT_USER_ID).strip() or DEFAULT_USER_ID


def store_brief(query: str, brief: Brief) -> None:
    """Persist a completed brief as a memory entry."""
    client = _get_client()
    if client is None:
        return
    summary_lines = [
        f"Query: {query}",
        f"Summary: {brief.executive_summary}",
        "Key findings:",
        *(f"- {f}" for f in brief.key_findings),
    ]
    text = "\n".join(summary_lines)
    metadata = {
        "query": query,
        "n_findings": len(brief.key_findings),
        "n_citations": len(brief.citations),
        "citation_urls": [str(c.candidate_url) for c in brief.citations][:20],
    }
    try:
        client.add(text, user_id=_user_id(), metadata=metadata)
        logger.info("mem0: stored brief for query %r (%d findings)", query[:60], len(brief.key_findings))
    except Exception as exc:
        logger.warning("mem0 store_brief failed: %s", exc)


def recall(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Return the top-K past memories most relevant to ``query``.

    Each item: {"text": "...", "metadata": {...}}. Empty list if disabled or empty.
    """
    client = _get_client()
    if client is None:
        return []
    try:
        results = client.search(query, user_id=_user_id())
    except Exception as exc:
        logger.warning("mem0 recall failed: %s", exc)
        return []

    # Mem0 returns either a list of dicts or {"results": [...]} depending on version.
    items = results.get("results", results) if isinstance(results, dict) else results
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    for item in items[:limit]:
        text = item.get("memory") or item.get("text") or ""
        meta = item.get("metadata") or {}
        if text:
            out.append({"text": text, "metadata": meta})
    return out


def reset_for_tests() -> None:
    """Reset cached state. Tests only."""
    global _enabled, _client
    _enabled = None
    _client = None
