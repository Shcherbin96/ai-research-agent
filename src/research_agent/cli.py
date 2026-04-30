"""Typer CLI: run the graph for a query and write a markdown brief to disk."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from research_agent.config import DEFAULT_LIMIT_PER_SOURCE, DEFAULT_TOP_N_SELECTED, load_settings
from research_agent.graph import build_graph
from research_agent.observability import (
    flush as langfuse_flush,
    is_enabled as langfuse_enabled,
    observe,
    update_current_trace,
)
from research_agent.render import brief_to_markdown

app = typer.Typer(add_completion=False, help="Technical Research Agent — produces a grounded brief.")


@app.command("eval")
def eval_cmd(
    task: Annotated[
        list[str] | None,
        typer.Option("--task", help="Run only these task ids (repeatable)."),
    ] = None,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Where to write report JSON + markdown.")
    ] = Path("eval/reports"),
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the eval suite and write a report."""
    import asyncio as _asyncio

    from research_agent.eval.runner import render_markdown, run_eval, write_report

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_settings()
    output_dir.mkdir(parents=True, exist_ok=True)

    typer.echo("Running eval...")
    report = _asyncio.run(run_eval(task_filter=task))

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"{timestamp}-report.json"
    md_path = output_dir / f"{timestamp}-report.md"
    write_report(report, json_path)
    md_path.write_text(render_markdown(report), encoding="utf-8")

    typer.echo(render_markdown(report))
    typer.echo(f"\nWrote {json_path}\nWrote {md_path}")


@app.command("eval-passk")
def eval_passk_cmd(
    task: Annotated[
        list[str] | None,
        typer.Option("--task", help="Run only these task ids (repeatable)."),
    ] = None,
    k: Annotated[int, typer.Option("--k", help="Number of runs per task (default 4).")] = 4,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Where to write report JSON + markdown.")
    ] = Path("eval/reports"),
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run pass^k reliability eval — each task k times, must pass all k."""
    import asyncio as _asyncio

    from research_agent.eval.runner import (
        render_pass_k_markdown,
        run_pass_k,
        write_report,
    )

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_settings()
    output_dir.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Running pass^{k} eval...")
    report = _asyncio.run(run_pass_k(k=k, task_filter=task))

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"{timestamp}-passk-report.json"
    md_path = output_dir / f"{timestamp}-passk-report.md"
    write_report(report, json_path)
    md_path.write_text(render_pass_k_markdown(report), encoding="utf-8")

    typer.echo(render_pass_k_markdown(report))
    typer.echo(f"\nWrote {json_path}\nWrote {md_path}")


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:max_len] or "query"


@observe(name="research_agent.run")
async def _run(state: dict) -> dict:
    graph = build_graph()
    update_current_trace(name=f"research: {state['query'][:80]}", input={"query": state["query"]})
    result = await graph.ainvoke(state)
    update_current_trace(
        output={
            "n_findings": len(result.get("brief").key_findings) if result.get("brief") else 0,
            "n_citations": len(result.get("brief").citations) if result.get("brief") else 0,
        },
    )
    return result


@app.command("run")
def run_cmd(
    query: Annotated[str, typer.Argument(help="Research query in natural language.")],
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Where to write the brief.")
    ] = Path("briefs"),
    limit_per_source: Annotated[
        int, typer.Option("--limit-per-source", help="Per-adapter result cap per subquery.")
    ] = DEFAULT_LIMIT_PER_SOURCE,
    top_n: Annotated[
        int, typer.Option("--top-n", help="Number of candidates to read in full.")
    ] = DEFAULT_TOP_N_SELECTED,
    no_web: Annotated[
        bool, typer.Option("--no-web", help="Skip Anthropic web_search adapter.")
    ] = False,
    scholar: Annotated[
        bool,
        typer.Option(
            "--scholar",
            help="Enable Google Scholar via Browserbase. Requires BROWSERBASE_API_KEY + _PROJECT_ID.",
        ),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the research pipeline and write a markdown brief."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    load_settings()  # fail fast on missing API key
    output_dir.mkdir(parents=True, exist_ok=True)

    initial_state = {
        "query": query,
        "errors": [],
        "use_web": not no_web,
        "use_scholar": scholar,
        "limit_per_source": limit_per_source,
        "top_n": top_n,
    }

    typer.echo(f"Running research pipeline for: {query!r}")
    if langfuse_enabled():
        typer.echo("Langfuse tracing: enabled")
    started = time.time()
    try:
        final = asyncio.run(_run(initial_state))
    finally:
        langfuse_flush()
    elapsed = time.time() - started

    brief = final.get("brief")
    if brief is None:
        typer.echo("Pipeline finished without producing a Brief. Check logs.", err=True)
        raise typer.Exit(code=1)

    md = brief_to_markdown(brief)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}-{_slugify(query)}.md"
    out_path = output_dir / filename
    out_path.write_text(md, encoding="utf-8")

    errors = final.get("errors") or []
    typer.echo(f"Wrote {out_path} ({elapsed:.1f}s)")
    typer.echo(
        f"  candidates={len(final.get('candidates') or [])} "
        f"selected={len(final.get('selected') or [])} "
        f"facts={len(final.get('facts') or [])} "
        f"citations={len(brief.citations)} "
        f"errors={len(errors)}"
    )
    if verbose and errors:
        for e in errors:
            typer.echo(f"  ! {e}", err=True)


if __name__ == "__main__":
    app()
