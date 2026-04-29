from datetime import datetime

from research_agent.models import Brief, Citation
from research_agent.render import brief_to_markdown


def _sample_brief() -> Brief:
    return Brief(
        query="agent memory approaches in 2025-2026",
        executive_summary=(
            "Episodic memory is the dominant pattern [1]. "
            "Vector stores remain a baseline [2]."
        ),
        key_findings=[
            "Mem0 introduces graph-augmented memory [1]",
            "Vector retrieval still wins on cost [2][3]",
        ],
        comparison_matrix=[
            {"approach": "Mem0", "idea": "graph + vectors [1]", "pros": "rich [1]"},
            {"approach": "Plain RAG", "idea": "vectors only [2]", "pros": "cheap [2]"},
        ],
        open_questions=["How do hybrid stores scale beyond 1M docs?"],
        citations=[
            Citation(
                index=1, candidate_url="https://arxiv.org/abs/2501.00001", title="Mem0 Paper"
            ),
            Citation(index=2, candidate_url="https://example.com/rag", title="RAG Blog"),
            Citation(index=3, candidate_url="https://github.com/x/y", title="x/y"),
        ],
    )


def test_render_contains_all_sections():
    md = brief_to_markdown(_sample_brief(), generated_at=datetime(2026, 4, 29, 12, 0, 0))
    for section in (
        "# agent memory approaches in 2025-2026",
        "## Executive Summary",
        "## Key Findings",
        "## Comparison Matrix",
        "## Open Questions",
        "## Citations",
        "Generated 2026-04-29T12:00:00",
    ):
        assert section in md, f"missing section: {section}"


def test_render_findings_have_citations():
    md = brief_to_markdown(_sample_brief())
    for line in md.splitlines():
        if line.startswith("- ") and "Mem0" in line:
            assert "[1]" in line


def test_render_matrix_table_format():
    md = brief_to_markdown(_sample_brief())
    assert "| approach | idea | pros |" in md
    assert "| --- | --- | --- |" in md


def test_render_handles_empty_brief():
    empty = Brief(query="empty test", executive_summary="")
    md = brief_to_markdown(empty)
    assert "_No summary produced._" in md
    assert "_No key findings produced._" in md
    assert "_No comparison matrix produced" in md
    assert "_No open questions._" in md
    assert "_No citations._" in md
