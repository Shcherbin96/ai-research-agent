"""Loads prompt files from the bundled ``prompts/`` directory.

Resolution order:
1. ``prompts/`` next to the package (development install / editable mode).
2. ``research_agent/prompts/`` inside the installed wheel (see pyproject force-include).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent

# Resolution order:
#   1. ``<repo>/prompts/`` — local editable install (src/research_agent → repo root)
#   2. ``<package_dir>/../prompts`` — Modal mount target (/root/prompts when the
#      package lives at /root/research_agent)
#   3. ``<package_dir>/prompts/`` — bundled wheel (see pyproject force-include)
_PROMPTS_CANDIDATES = (
    _PACKAGE_DIR.parent.parent / "prompts",
    _PACKAGE_DIR.parent / "prompts",
    _PACKAGE_DIR / "prompts",
)


def _resolve_dir() -> Path:
    for candidate in _PROMPTS_CANDIDATES:
        if candidate.is_dir():
            return candidate
    paths = ", ".join(str(p) for p in _PROMPTS_CANDIDATES)
    raise FileNotFoundError(f"prompts/ not found at any of: {paths}")


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load ``prompts/<name>.md`` and return its raw text."""
    path = _resolve_dir() / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
