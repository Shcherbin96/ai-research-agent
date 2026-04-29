"""Thin wrappers around the Anthropic SDK used by graph nodes.

We expose three call helpers and one parsing helper:
- ``call_sonnet`` / ``call_haiku``: synchronous text completion with optional JSON tag parsing.
- ``call_with_web_search``: invoke Sonnet with the server-side ``web_search`` tool and
  return a flat list of ``{url, title, snippet}`` dicts gathered from the tool results.
- ``extract_json_tag``: pulls the inner payload of ``<json>...</json>`` and parses it.

Anthropic does not offer strict JSON output mode, so prompts are written to wrap
their payload in ``<json>`` tags. ``extract_json_tag`` is forgiving: it falls back
to extracting the first ``{...}`` or ``[...]`` block if the tag is missing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from anthropic import Anthropic

from research_agent.config import (
    HAIKU_MODEL,
    SONNET_MODEL,
    WEB_SEARCH_TOOL_TYPE,
    load_settings,
)
from research_agent.observability import observe, update_current_observation

_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        settings = load_settings()
        # max_retries=4 + the SDK's exponential backoff is the safety net for 429s
        # that slip past per-node concurrency throttling.
        _client = Anthropic(api_key=settings.anthropic_api_key, max_retries=4)
    return _client


def _collect_text(content_blocks: list[Any]) -> str:
    parts: list[str] = []
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _record_usage(model: str, system: str, user: str, response: Any, output: str) -> None:
    """Attach Anthropic usage data to the current Langfuse observation."""
    try:
        usage = getattr(response, "usage", None)
        usage_details = (
            {
                "input": getattr(usage, "input_tokens", None),
                "output": getattr(usage, "output_tokens", None),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            }
            if usage is not None
            else None
        )
        update_current_observation(
            model=model,
            input={"system": system, "user": user},
            output=output,
            usage_details=usage_details,
        )
    except Exception:
        pass


@observe(name="call_sonnet")
def call_sonnet(
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """Synchronous Sonnet completion. Returns concatenated text content."""
    response = get_client().messages.create(
        model=SONNET_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = _collect_text(response.content)
    _record_usage(SONNET_MODEL, system, user, response, text)
    return text


@observe(name="call_haiku")
def call_haiku(
    *,
    system: str,
    user: str,
    max_tokens: int = 2048,
    temperature: float = 0.0,
) -> str:
    response = get_client().messages.create(
        model=HAIKU_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = _collect_text(response.content)
    _record_usage(HAIKU_MODEL, system, user, response, text)
    return text


@observe(name="call_with_web_search")
def call_with_web_search(
    *,
    query: str,
    max_uses: int = 3,
    max_tokens: int = 2048,
) -> list[dict[str, Any]]:
    """Run Sonnet with the server-side ``web_search`` tool and return raw results.

    The Anthropic API executes the search server-side. The assistant turn comes back
    with one or more ``web_search_tool_result`` content blocks; each carries a
    ``content`` list of items with at least ``url``, ``title``, and an
    ``encrypted_content`` snippet. We flatten and dedupe by URL.
    """
    response = get_client().messages.create(
        model=SONNET_MODEL,
        max_tokens=max_tokens,
        system=(
            "You are a research assistant. Use the web_search tool to find sources "
            "for the user's query. Do not summarize — the caller wants the raw search "
            "results, which the tool returns directly."
        ),
        messages=[{"role": "user", "content": f"Search the web for: {query}"}],
        tools=[{"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": max_uses}],
    )

    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for block in response.content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        block_content = getattr(block, "content", None)
        if not isinstance(block_content, list):
            continue
        for item in block_content:
            url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
            title = (
                item.get("title") if isinstance(item, dict) else getattr(item, "title", None)
            )
            snippet_raw = (
                item.get("encrypted_content")
                if isinstance(item, dict)
                else getattr(item, "encrypted_content", None)
            )
            page_age = (
                item.get("page_age")
                if isinstance(item, dict)
                else getattr(item, "page_age", None)
            )
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            items.append(
                {
                    "url": url,
                    "title": title or url,
                    "snippet": (snippet_raw or "")[:500],
                    "page_age": page_age,
                }
            )
    return items


_JSON_TAG_RE = re.compile(r"<json>(.*?)</json>", re.DOTALL | re.IGNORECASE)


def extract_json_tag(text: str) -> Any:
    """Parse JSON from a model response.

    Order of attempts:
    1. Inner of ``<json>...</json>`` tags.
    2. The first balanced ``{...}`` or ``[...]`` block.

    Raises ``ValueError`` with the offending text if parsing fails.
    """
    match = _JSON_TAG_RE.search(text)
    if match:
        payload = match.group(1).strip()
        return json.loads(payload)

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not extract JSON from model response:\n{text[:500]}")
