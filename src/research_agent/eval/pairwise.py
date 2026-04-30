"""Pairwise usefulness comparison via LLM-as-judge.

Given two briefs A and B on the same query, ask Sonnet which is more useful for an
AI engineer. Aggregate the win rate across N tasks.

Two ways to use it:

1. **Compare two brief sets you already have.** Call ``compare_briefs(a_path, b_path)``
   pointing at directories of briefs (one .json per task) keyed by task id.

2. **Run two agent configurations and compare.** ``run_pairwise`` invokes the
   pipeline twice per task (once with the "challenger" config, once with the
   "baseline" config) and judges the resulting briefs.

Position bias mitigation: each pair is judged TWICE with A and B swapped, and only
counted as a win if the same side wins both orderings. This is the standard
treatment from MT-Bench (Zheng et al., 2023).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from research_agent.eval.dataset import EvalTask, load_dataset
from research_agent.graph import build_graph
from research_agent.llm import call_sonnet, extract_json_tag
from research_agent.models import Brief
from research_agent.render import brief_to_markdown

logger = logging.getLogger(__name__)


_JUDGE_SYSTEM = """You compare two technical research briefs side by side and decide which is more useful for an AI engineer.

A brief is more useful when it:
1. Has more grounded claims (every claim ends with a citation marker like [n])
2. Surfaces a wider variety of approaches / sources
3. Has a comparison matrix that meaningfully contrasts options
4. Names specific methods/numbers/systems instead of generic statements
5. Covers a useful set of open questions

Be conservative — if both briefs are roughly comparable, prefer "tie" over picking arbitrarily.

Output a single `<json>` block:

<json>
{"verdict": "A|B|tie", "reason": "<20 words>"}
</json>
"""


Verdict = Literal["A", "B", "tie"]


def _judge_pair(query: str, brief_a_md: str, brief_b_md: str) -> tuple[Verdict, str]:
    user = (
        f"Query: {query}\n\n"
        f"## Brief A\n\n{brief_a_md}\n\n"
        f"## Brief B\n\n{brief_b_md}\n\n"
        f"Which brief is more useful?"
    )
    raw = call_sonnet(system=_JUDGE_SYSTEM, user=user, max_tokens=200, temperature=0.0)
    payload = extract_json_tag(raw)
    verdict = payload.get("verdict", "tie")
    if verdict not in ("A", "B", "tie"):
        verdict = "tie"
    return verdict, payload.get("reason", "")[:200]


def _consensus(query: str, brief_x_md: str, brief_y_md: str) -> tuple[Verdict, str]:
    """Judge twice with X/Y swapped. Only count a win if the same logical side wins
    both orderings; otherwise tie. Mitigates position bias."""
    v1, r1 = _judge_pair(query, brief_x_md, brief_y_md)  # X=A, Y=B
    v2, r2 = _judge_pair(query, brief_y_md, brief_x_md)  # Y=A, X=B
    # Map results back to {x, y, tie}
    side1 = {"A": "x", "B": "y", "tie": "tie"}[v1]
    side2 = {"A": "y", "B": "x", "tie": "tie"}[v2]
    if side1 == side2 and side1 != "tie":
        winner = side1
    elif side1 == "tie" and side2 != "tie":
        winner = side2
    elif side2 == "tie" and side1 != "tie":
        winner = side1
    else:
        winner = "tie"
    # Re-encode as A/B from caller's perspective: x=A (challenger), y=B (baseline)
    out: Verdict = {"x": "A", "y": "B", "tie": "tie"}[winner]
    return out, f"order1={v1}({r1}); order2={v2}({r2})"


@dataclass
class PairwiseResult:
    task_id: str
    kind: str
    query: str
    challenger_findings: int
    baseline_findings: int
    verdict: Verdict
    reason: str


@dataclass
class PairwiseReport:
    started_at: str
    finished_at: str
    n_tasks: int
    challenger_label: str
    baseline_label: str
    challenger_wins: int
    baseline_wins: int
    ties: int
    win_rate: float  # challenger wins / (wins + losses), ties excluded
    results: list[PairwiseResult] = field(default_factory=list)


async def _run_pipeline(query: str) -> Brief | None:
    graph = build_graph()
    state = {
        "query": query,
        "errors": [],
        "use_web": True,
        "limit_per_source": 6,
        "top_n": 6,
    }
    final = await graph.ainvoke(state)
    return final.get("brief")


def _slim_brief_md(brief: Brief | None) -> str:
    if brief is None:
        return "_No brief produced._"
    return brief_to_markdown(brief)


_TASK_ID_RE = re.compile(r"[^a-z0-9-]+")


def _norm_id(s: str) -> str:
    return _TASK_ID_RE.sub("-", s.lower()).strip("-")


def compare_briefs(
    challenger_dir: Path,
    baseline_dir: Path,
    challenger_label: str = "challenger",
    baseline_label: str = "baseline",
) -> PairwiseReport:
    """Compare two pre-computed brief sets. Each dir contains ``<task-id>.json`` files
    (each holding a serialised ``Brief``). Tasks present in both dirs are judged.
    """
    chall_files = {p.stem: p for p in challenger_dir.glob("*.json")}
    base_files = {p.stem: p for p in baseline_dir.glob("*.json")}
    common = sorted(set(chall_files) & set(base_files))
    if not common:
        raise ValueError(
            f"No shared task ids between {challenger_dir} and {baseline_dir}"
        )

    started = datetime.now()
    results: list[PairwiseResult] = []
    for task_id in common:
        c_brief = Brief.model_validate_json(chall_files[task_id].read_text(encoding="utf-8"))
        b_brief = Brief.model_validate_json(base_files[task_id].read_text(encoding="utf-8"))
        verdict, reason = _consensus(
            c_brief.query, _slim_brief_md(c_brief), _slim_brief_md(b_brief)
        )
        results.append(
            PairwiseResult(
                task_id=task_id,
                kind="?",
                query=c_brief.query,
                challenger_findings=len(c_brief.key_findings),
                baseline_findings=len(b_brief.key_findings),
                verdict=verdict,
                reason=reason,
            )
        )

    return _aggregate(results, started, challenger_label, baseline_label)


async def run_pairwise(
    challenger_label: str,
    baseline_label: str,
    challenger_runner,
    baseline_runner,
    task_filter: list[str] | None = None,
    dataset_path: Path | None = None,
) -> PairwiseReport:
    """Run two agent configurations on the same tasks and judge each pair.

    ``challenger_runner`` and ``baseline_runner`` are async callables that take
    an ``EvalTask`` and return a ``Brief | None``.
    """
    ds = load_dataset(dataset_path)
    tasks: list[EvalTask] = ds.tasks
    if task_filter:
        wanted = set(task_filter)
        tasks = [t for t in tasks if t.id in wanted]

    started = datetime.now()
    results: list[PairwiseResult] = []
    for i, task in enumerate(tasks):
        if i > 0:
            await asyncio.sleep(45)
        logger.info("pairwise: task %s — running challenger", task.id)
        c_brief = await challenger_runner(task)
        await asyncio.sleep(45)
        logger.info("pairwise: task %s — running baseline", task.id)
        b_brief = await baseline_runner(task)
        verdict, reason = _consensus(task.query, _slim_brief_md(c_brief), _slim_brief_md(b_brief))
        results.append(
            PairwiseResult(
                task_id=task.id,
                kind=task.kind,
                query=task.query,
                challenger_findings=len(c_brief.key_findings) if c_brief else 0,
                baseline_findings=len(b_brief.key_findings) if b_brief else 0,
                verdict=verdict,
                reason=reason,
            )
        )

    return _aggregate(results, started, challenger_label, baseline_label)


def _aggregate(
    results: list[PairwiseResult],
    started: datetime,
    challenger_label: str,
    baseline_label: str,
) -> PairwiseReport:
    challenger_wins = sum(1 for r in results if r.verdict == "A")
    baseline_wins = sum(1 for r in results if r.verdict == "B")
    ties = sum(1 for r in results if r.verdict == "tie")
    decided = challenger_wins + baseline_wins
    win_rate = (challenger_wins / decided) if decided else 0.0

    return PairwiseReport(
        started_at=started.isoformat(timespec="seconds"),
        finished_at=datetime.now().isoformat(timespec="seconds"),
        n_tasks=len(results),
        challenger_label=challenger_label,
        baseline_label=baseline_label,
        challenger_wins=challenger_wins,
        baseline_wins=baseline_wins,
        ties=ties,
        win_rate=win_rate,
        results=results,
    )


def render_markdown(report: PairwiseReport) -> str:
    lines = [
        "# Pairwise comparison",
        "",
        f"- Started: {report.started_at}",
        f"- Finished: {report.finished_at}",
        f"- Tasks: {report.n_tasks}",
        f"- **Challenger:** `{report.challenger_label}`",
        f"- **Baseline:** `{report.baseline_label}`",
        "",
        f"**Challenger win rate (ties excluded): {report.win_rate:.2%}**",
        "",
        f"- Challenger wins: {report.challenger_wins}",
        f"- Baseline wins: {report.baseline_wins}",
        f"- Ties: {report.ties}",
        "",
        "## Per-task",
        "",
        "| id | verdict | challenger findings | baseline findings | reason |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for r in report.results:
        symbol = {"A": "🟢 challenger", "B": "🔴 baseline", "tie": "⚪ tie"}[r.verdict]
        reason = r.reason.replace("|", "\\|")[:120]
        lines.append(
            f"| `{r.task_id}` | {symbol} | {r.challenger_findings} | "
            f"{r.baseline_findings} | {reason} |"
        )
    return "\n".join(lines) + "\n"


def write_report(report: PairwiseReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**asdict(report)}, indent=2, default=str), encoding="utf-8")
