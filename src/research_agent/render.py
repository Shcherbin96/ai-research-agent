"""Render a ``Brief`` to a portable Markdown document."""

from __future__ import annotations

from datetime import datetime

from research_agent.models import Brief


def _matrix_to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "_No comparison matrix produced — facts were insufficient._"

    keys: list[str] = []
    for row in rows:
        for k in row.keys():
            if k not in keys:
                keys.append(k)

    header = "| " + " | ".join(keys) + " |"
    separator = "| " + " | ".join("---" for _ in keys) + " |"
    body_lines = []
    for row in rows:
        cells = [str(row.get(k, "")).replace("\n", " ").replace("|", "\\|") for k in keys]
        body_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, separator, *body_lines])


def brief_to_markdown(brief: Brief, *, generated_at: datetime | None = None) -> str:
    when = (generated_at or datetime.now()).isoformat(timespec="seconds")

    findings = (
        "\n".join(f"- {f}" for f in brief.key_findings)
        if brief.key_findings
        else "_No key findings produced._"
    )
    questions = (
        "\n".join(f"- {q}" for q in brief.open_questions)
        if brief.open_questions
        else "_No open questions._"
    )

    citation_lines: list[str] = []
    for c in sorted(brief.citations, key=lambda x: x.index):
        line = f"[{c.index}] {c.title} — <{c.candidate_url}>"
        if c.quote:
            line += f"\n    > {c.quote}"
        citation_lines.append(line)
    citations_block = "\n".join(citation_lines) if citation_lines else "_No citations._"

    return (
        f"# {brief.query}\n\n"
        f"> Generated {when}\n\n"
        f"## Executive Summary\n\n"
        f"{brief.executive_summary or '_No summary produced._'}\n\n"
        f"## Key Findings\n\n"
        f"{findings}\n\n"
        f"## Comparison Matrix\n\n"
        f"{_matrix_to_markdown(brief.comparison_matrix)}\n\n"
        f"## Open Questions\n\n"
        f"{questions}\n\n"
        f"## Citations\n\n"
        f"{citations_block}\n"
    )
