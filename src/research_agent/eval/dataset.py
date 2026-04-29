"""Eval dataset schema + loader.

A task is one of two kinds:

- ``synthetic`` — a query for which we have a ground-truth list of URLs that *should*
  appear among the brief's citations. Used for **recall** measurement.
- ``real`` — a query pulled from a real source (Twitter/Reddit/HN/etc.) without a
  pre-known answer set. We only measure **support rate** (LLM-as-judge on each
  claim/citation pair).

The dataset lives at ``eval/tasks.json`` so it's reviewable in git diffs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class EvalTask(BaseModel):
    id: str
    kind: Literal["synthetic", "real"]
    query: str
    notes: str = ""
    must_have_urls: list[str] = Field(default_factory=list)
    """For synthetic tasks: URLs that a competent run *should* surface."""
    source: str = ""
    """For real tasks: where the question came from (e.g. Twitter URL)."""


class EvalDataset(BaseModel):
    version: str
    tasks: list[EvalTask]


_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "eval" / "tasks.json"


def load_dataset(path: Path | None = None) -> EvalDataset:
    p = path or _DEFAULT_PATH
    if not p.is_file():
        raise FileNotFoundError(f"Eval dataset not found at {p}")
    return EvalDataset.model_validate_json(p.read_text(encoding="utf-8"))


def save_dataset(ds: EvalDataset, path: Path | None = None) -> Path:
    p = path or _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ds.model_dump(mode="json"), indent=2), encoding="utf-8")
    return p
