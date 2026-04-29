"""Loads prompt files from the bundled ``prompts/`` directory.

Resolution order:
1. ``prompts/`` next to the package (development install / editable mode).
2. ``research_agent/prompts/`` inside the installed wheel (see pyproject force-include).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEV_PROMPTS_DIR = _PACKAGE_DIR.parent.parent / "prompts"
_BUNDLED_PROMPTS_DIR = _PACKAGE_DIR / "prompts"


def _resolve_dir() -> Path:
    if _DEV_PROMPTS_DIR.is_dir():
        return _DEV_PROMPTS_DIR
    if _BUNDLED_PROMPTS_DIR.is_dir():
        return _BUNDLED_PROMPTS_DIR
    raise FileNotFoundError(
        f"prompts/ not found at {_DEV_PROMPTS_DIR} or {_BUNDLED_PROMPTS_DIR}"
    )


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load ``prompts/<name>.md`` and return its raw text."""
    path = _resolve_dir() / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
