"""Optional Langfuse integration.

If ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set in the environment,
node functions and LLM calls report to Langfuse via the ``@observe`` decorator
and ``update_current_observation`` calls. If keys are missing, ``observe`` becomes
a no-op pass-through so the agent runs unchanged.

This keeps tracing strictly opt-in — CI runs and local development without a
Langfuse account work without changes.
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_enabled: bool | None = None


def _resolve_enabled() -> bool:
    global _enabled
    if _enabled is not None:
        return _enabled
    has_keys = bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )
    _enabled = has_keys
    if has_keys:
        logger.info("Langfuse tracing enabled (host=%s)", os.environ.get("LANGFUSE_HOST", "cloud"))
    else:
        logger.debug("Langfuse keys not set — tracing disabled")
    return has_keys


def is_enabled() -> bool:
    return _resolve_enabled()


def observe(name: str | None = None) -> Callable[[F], F]:
    """Trace a function as a Langfuse span. No-op if Langfuse is disabled."""
    if not _resolve_enabled():
        def passthrough(fn: F) -> F:
            return fn
        return passthrough

    from langfuse import observe as _observe

    return _observe(name=name) if name else _observe()


def update_current_observation(**kwargs: Any) -> None:
    """Attach data (input/output/model/usage) to the current span. No-op if disabled."""
    if not _resolve_enabled():
        return
    try:
        from langfuse import get_client

        get_client().update_current_observation(**kwargs)
    except Exception as exc:
        logger.debug("langfuse update_current_observation failed: %s", exc)


def update_current_trace(**kwargs: Any) -> None:
    """Attach trace-level metadata (e.g. user_id, session_id, name)."""
    if not _resolve_enabled():
        return
    try:
        from langfuse import get_client

        get_client().update_current_trace(**kwargs)
    except Exception as exc:
        logger.debug("langfuse update_current_trace failed: %s", exc)


def flush() -> None:
    """Force-flush queued events. Call before process exit."""
    if not _resolve_enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as exc:
        logger.debug("langfuse flush failed: %s", exc)


def reset_for_tests() -> None:
    """Reset the cached enabled flag. Tests only."""
    global _enabled
    _enabled = None


@functools.lru_cache(maxsize=1)
def _warn_anthropic_token_format_once(model: str) -> None:
    logger.debug("recording usage for first call to %s", model)
