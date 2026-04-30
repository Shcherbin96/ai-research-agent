from datetime import datetime

from research_agent.eval.pairwise import (
    PairwiseReport,
    PairwiseResult,
    _aggregate,
    render_markdown,
)


def test_aggregate_win_rate_excludes_ties():
    results = [
        PairwiseResult(task_id="a", kind="syn", query="q", challenger_findings=5,
                       baseline_findings=3, verdict="A", reason="r"),
        PairwiseResult(task_id="b", kind="syn", query="q", challenger_findings=4,
                       baseline_findings=4, verdict="A", reason="r"),
        PairwiseResult(task_id="c", kind="syn", query="q", challenger_findings=2,
                       baseline_findings=5, verdict="B", reason="r"),
        PairwiseResult(task_id="d", kind="syn", query="q", challenger_findings=4,
                       baseline_findings=4, verdict="tie", reason="r"),
    ]
    report = _aggregate(results, datetime(2026, 4, 30), "v2", "v1")
    assert report.challenger_wins == 2
    assert report.baseline_wins == 1
    assert report.ties == 1
    # 2 wins out of 3 decided games
    assert abs(report.win_rate - 2 / 3) < 1e-9


def test_render_markdown_includes_labels_and_emoji():
    report = PairwiseReport(
        started_at="2026-04-30T10:00:00",
        finished_at="2026-04-30T10:30:00",
        n_tasks=2,
        challenger_label="prompt-v2",
        baseline_label="prompt-v1",
        challenger_wins=1,
        baseline_wins=1,
        ties=0,
        win_rate=0.5,
        results=[
            PairwiseResult(task_id="x", kind="syn", query="q1",
                           challenger_findings=8, baseline_findings=6,
                           verdict="A", reason="more grounded"),
            PairwiseResult(task_id="y", kind="real", query="q2",
                           challenger_findings=5, baseline_findings=7,
                           verdict="B", reason="broader matrix"),
        ],
    )
    md = render_markdown(report)
    assert "prompt-v2" in md
    assert "prompt-v1" in md
    assert "win rate (ties excluded): 50.00%" in md
    assert "🟢 challenger" in md
    assert "🔴 baseline" in md


def test_render_markdown_tie_only():
    report = PairwiseReport(
        started_at="2026-04-30T10:00:00",
        finished_at="2026-04-30T10:30:00",
        n_tasks=1,
        challenger_label="A",
        baseline_label="B",
        challenger_wins=0,
        baseline_wins=0,
        ties=1,
        win_rate=0.0,
        results=[
            PairwiseResult(task_id="t", kind="syn", query="q",
                           challenger_findings=5, baseline_findings=5,
                           verdict="tie", reason="comparable"),
        ],
    )
    md = render_markdown(report)
    assert "⚪ tie" in md
