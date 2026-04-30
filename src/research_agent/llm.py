"""Thin wrappers around the Anthropic SDK used by graph nodes.

We expose three call helpers and one parsing helper:
- ``call_sonnet`` / ``call_haiku``: synchronous text completion with optional JSON tag parsing.
- ``call_with_web_search``: invoke Sonnet with the server-side ``web_search`` tool and
  return a flat list of ``{url, title, snippet}`` dicts gathered from the tool results.
- ``extract_json_tag``: pulls the inner payload of ``<json>...</json>`` and parses it.

Anthropic does not offer strict JSON output mode, so prompts are written to wrap
their payload in ``<json>`` tags. ``extract_json_tag`` is forgiving: it falls back
to extracting the first ``{...}`` or ``[...]`` block if the tag is missing.

Both call helpers accept ``cache_system: bool`` — when True, the system prompt is
sent with ``cache_control: {"type": "ephemeral"}`` so subsequent calls within the
5-minute Anthropic cache TTL pay 10% input-token cost on the system portion. This
matters most for ``read_node`` which fires 5-10 calls per query with the same
~1500-token system prompt — typical savings are 60-80% on input cost.
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
        # max_retries=6 with exponential backoff (1+2+4+8+16+32 = 63s) is enough
        # for the Anthropic Tier-1 30k-tokens/min budget to reset once mid-retry,
        # which is what we need when read_node bursts past the cap on cloud IPs.
        _client = Anthropic(api_key=settings.anthropic_api_key, max_retries=6)
    return _client


def _collect_text(content_blocks: list[Any]) -> str:
    parts: list[str] = []
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


# --- Pricing (April 2026, USD per million tokens) ---
# Verified via context7 mid-implementation. If Anthropic publishes new tiers,
# update these — they're public, no API call needed at runtime.
_PRICING = {
    SONNET_MODEL: {
        "input": 3.00,
        "output": 15.00,
        "cache_write_5m": 3.75,    # cache writes cost 1.25x input
        "cache_read": 0.30,         # cache reads cost 0.10x input
    },
    HAIKU_MODEL: {
        "input": 1.00,
        "output": 5.00,
        "cache_write_5m": 1.25,
        "cache_read": 0.10,
    },
}


def _system_with_cache(system: str) -> list[dict[str, Any]]:
    """Wrap a plain system string into the cacheable block list form."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    return {
        "input": getattr(usage, "input_tokens", 0) or 0,
        "output": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def estimate_cost_usd(model: str, usage: dict[str, int]) -> dict[str, float]:
    """Return a per-call cost breakdown in USD given a usage dict from Anthropic."""
    rates = _PRICING.get(model)
    if rates is None:
        return {"input": 0.0, "output": 0.0, "cache_write": 0.0, "cache_read": 0.0, "total": 0.0}
    input_cost = (usage["input"] / 1_000_000) * rates["input"]
    output_cost = (usage["output"] / 1_000_000) * rates["output"]
    cache_write = (usage["cache_creation"] / 1_000_000) * rates["cache_write_5m"]
    cache_read = (usage["cache_read"] / 1_000_000) * rates["cache_read"]
    return {
        "input": input_cost,
        "output": output_cost,
        "cache_write": cache_write,
        "cache_read": cache_read,
        "total": input_cost + output_cost + cache_write + cache_read,
    }


_RUN_USAGE_KEY = "__run_usage__"


def get_run_usage() -> dict[str, Any]:
    """Module-level accumulator. Reset before each pipeline run via ``reset_run_usage``."""
    return globals().setdefault(_RUN_USAGE_KEY, {"calls": [], "total_cost_usd": 0.0})


def reset_run_usage() -> None:
    globals()[_RUN_USAGE_KEY] = {"calls": [], "total_cost_usd": 0.0}


def _record_usage(
    *,
    model: str,
    system: str,
    user: str,
    response: Any,
    output: str,
    node: str | None = None,
) -> None:
    """Attach Anthropic usage to the Langfuse span and to the run-level accumulator."""
    usage = _usage_dict(response)
    cost = estimate_cost_usd(model, usage)

    # Langfuse
    try:
        update_current_observation(
            model=model,
            input={"system": system, "user": user},
            output=output,
            usage_details=usage,
        )
    except Exception:
        pass

    # Run accumulator
    bucket = get_run_usage()
    bucket["calls"].append(
        {"node": node, "model": model, "usage": usage, "cost_usd": cost}
    )
    bucket["total_cost_usd"] += cost["total"]


@observe(name="call_sonnet")
def call_sonnet(
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    cache_system: bool = False,
    node: str | None = None,
) -> str:
    """Synchronous Sonnet completion. Returns concatenated text content.

    ``cache_system=True`` flags the system prompt as cacheable for 5 minutes.
    Use this when the same large system prompt is repeated across many calls
    (e.g. read_node fires it 5-10 times per query).
    """
    response = get_client().messages.create(
        model=SONNET_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=_system_with_cache(system) if cache_system else system,
        messages=[{"role": "user", "content": user}],
    )
    text = _collect_text(response.content)
    _record_usage(model=SONNET_MODEL, system=system, user=user, response=response,
                  output=text, node=node)
    return text


@observe(name="stream_sonnet")
def stream_sonnet(
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    cache_system: bool = False,
    node: str | None = None,
):
    """Yield text chunks from Sonnet as they arrive. Records usage on close."""
    full_text: list[str] = []
    final_message: Any = None

    with get_client().messages.stream(
        model=SONNET_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=_system_with_cache(system) if cache_system else system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for chunk in stream.text_stream:
            full_text.append(chunk)
            yield chunk
        final_message = stream.get_final_message()

    text = "".join(full_text)
    if final_message is not None:
        _record_usage(model=SONNET_MODEL, system=system, user=user, response=final_message,
                      output=text, node=node)


@observe(name="call_haiku")
def call_haiku(
    *,
    system: str,
    user: str,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    cache_system: bool = False,
    node: str | None = None,
) -> str:
    response = get_client().messages.create(
        model=HAIKU_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=_system_with_cache(system) if cache_system else system,
        messages=[{"role": "user", "content": user}],
    )
    text = _collect_text(response.content)
    _record_usage(model=HAIKU_MODEL, system=system, user=user, response=response,
                  output=text, node=node)
    return text


@observe(name="call_with_web_search")
def call_with_web_search(
    *,
    query: str,
    max_uses: int = 3,
    max_tokens: int = 2048,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Run a model with the server-side ``web_search`` tool and return raw results.

    Defaults to Haiku 4.5 — the model just dispatches the tool call and returns
    raw results, no reasoning needed. Caller can override via ``model``.
    """
    response = get_client().messages.create(
        model=model or HAIKU_MODEL,
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
