"""Eval harness — run the agent on each task, score, aggregate, and report.

Single-pass: one run per task. ``pass^4`` (4 runs, all-must-pass) is a future
extension when reliability becomes the bottleneck.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from research_agent.eval.dataset import EvalTask, load_dataset
from research_agent.eval.judge import judge_brief, support_rate
from research_agent.graph import build_graph
from research_agent.models import Brief

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    task_id: str
    kind: str
    query: str
    duration_sec: float
    n_candidates: int
    n_selected: int
    n_facts: int
    n_findings: int
    n_citations: int
    support_rate: float
    recall: float | None  # None for real tasks
    matched_must_have: list[str] = field(default_factory=list)
    missed_must_have: list[str] = field(default_factory=list)
    verdicts: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    started_at: str
    finished_at: str
    n_tasks: int
    avg_support_rate: float
    avg_recall: float | None
    results: list[TaskResult]


def _normalize(url: str) -> str:
    return url.lower().rstrip("/").replace("http://", "https://")


def _recall(must_have: list[str], brief: Brief) -> tuple[float, list[str], list[str]]:
    if not must_have:
        return 1.0, [], []
    cited = {_normalize(str(c.candidate_url)) for c in brief.citations}
    candidates_in_findings = " ".join(brief.key_findings) + " " + brief.executive_summary
    matched: list[str] = []
    missed: list[str] = []
    for url in must_have:
        n = _normalize(url)
        if n in cited or n in candidates_in_findings.lower():
            matched.append(url)
        else:
            missed.append(url)
    return len(matched) / len(must_have), matched, missed


async def _run_one(task: EvalTask) -> TaskResult:
    started = datetime.now()
    graph = build_graph()
    state = {
        "query": task.query,
        "errors": [],
        "use_web": True,
        "limit_per_source": 10,
        "top_n": 10,
    }

    final = await graph.ainvoke(state)
    duration = (datetime.now() - started).total_seconds()

    brief: Brief | None = final.get("brief")
    errors = list(final.get("errors") or [])

    if brief is None or not brief.key_findings:
        return TaskResult(
            task_id=task.id,
            kind=task.kind,
            query=task.query,
            duration_sec=duration,
            n_candidates=len(final.get("candidates") or []),
            n_selected=len(final.get("selected") or []),
            n_facts=len(final.get("facts") or []),
            n_findings=0,
            n_citations=0,
            support_rate=0.0,
            recall=0.0 if task.kind == "synthetic" else None,
            errors=errors + ["empty brief"],
        )

    verdicts = await judge_brief(brief)
    sr = support_rate(verdicts)
    rec, matched, missed = (
        _recall(task.must_have_urls, brief) if task.kind == "synthetic" else (None, [], [])
    )

    return TaskResult(
        task_id=task.id,
        kind=task.kind,
        query=task.query,
        duration_sec=duration,
        n_candidates=len(final.get("candidates") or []),
        n_selected=len(final.get("selected") or []),
        n_facts=len(final.get("facts") or []),
        n_findings=len(brief.key_findings),
        n_citations=len(brief.citations),
        support_rate=sr,
        recall=rec,
        matched_must_have=matched,
        missed_must_have=missed,
        verdicts=[v.model_dump(mode="json") for v in verdicts],
        errors=errors,
    )


async def run_eval(
    task_filter: list[str] | None = None,
    dataset_path: Path | None = None,
) -> EvalReport:
    ds = load_dataset(dataset_path)
    tasks = ds.tasks
    if task_filter:
        wanted = set(task_filter)
        tasks = [t for t in tasks if t.id in wanted]
        if not tasks:
            raise ValueError(f"No tasks matched filter {task_filter}")

    started = datetime.now()
    results: list[TaskResult] = []
    for task in tasks:
        logger.info("eval: running %s (%s)", task.id, task.kind)
        try:
            r = await _run_one(task)
        except Exception as exc:
            logger.exception("eval: task %s crashed", task.id)
            r = TaskResult(
                task_id=task.id,
                kind=task.kind,
                query=task.query,
                duration_sec=0.0,
                n_candidates=0,
                n_selected=0,
                n_facts=0,
                n_findings=0,
                n_citations=0,
                support_rate=0.0,
                recall=0.0 if task.kind == "synthetic" else None,
                errors=[f"crash: {exc!r}"],
            )
        results.append(r)
        logger.info(
            "eval: %s done — support=%.2f recall=%s findings=%d (%.1fs)",
            r.task_id,
            r.support_rate,
            f"{r.recall:.2f}" if r.recall is not None else "—",
            r.n_findings,
            r.duration_sec,
        )

    avg_support = sum(r.support_rate for r in results) / len(results) if results else 0.0
    syn = [r.recall for r in results if r.recall is not None]
    avg_recall = sum(syn) / len(syn) if syn else None

    return EvalReport(
        started_at=started.isoformat(timespec="seconds"),
        finished_at=datetime.now().isoformat(timespec="seconds"),
        n_tasks=len(results),
        avg_support_rate=avg_support,
        avg_recall=avg_recall,
        results=results,
    )


def write_report(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({**asdict(report)}, indent=2, default=str),
        encoding="utf-8",
    )


def render_markdown(report: EvalReport) -> str:
    lines = [
        "# Eval report",
        "",
        f"- Started: {report.started_at}",
        f"- Finished: {report.finished_at}",
        f"- Tasks: {report.n_tasks}",
        f"- **Avg support rate: {report.avg_support_rate:.2%}**",
    ]
    if report.avg_recall is not None:
        lines.append(f"- **Avg recall (synthetic): {report.avg_recall:.2%}**")
    lines.extend(["", "## Per-task", "", "| id | kind | findings | support | recall | duration |", "| --- | --- | ---: | ---: | ---: | ---: |"])
    for r in report.results:
        rec = f"{r.recall:.0%}" if r.recall is not None else "—"
        lines.append(
            f"| `{r.task_id}` | {r.kind} | {r.n_findings} | "
            f"{r.support_rate:.0%} | {rec} | {r.duration_sec:.0f}s |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    """Standalone entry: ``python -m research_agent.eval.runner``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    report = asyncio.run(run_eval())
    print(render_markdown(report))


if __name__ == "__main__":
    main()
