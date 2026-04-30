from research_agent.eval.runner import (
    PassKReport,
    PassKResult,
    TaskResult,
    _is_passing,
    render_pass_k_markdown,
)


def _make_run(
    *, support: float, recall: float | None, findings: int, task_id: str = "t"
) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        kind="synthetic" if recall is not None else "real",
        query="q",
        duration_sec=10,
        n_candidates=10,
        n_selected=5,
        n_facts=5,
        n_findings=findings,
        n_citations=findings,
        support_rate=support,
        recall=recall,
    )


def test_is_passing_high_support_high_recall():
    r = _make_run(support=0.9, recall=0.7, findings=8)
    assert _is_passing(r) is True


def test_is_passing_blocks_low_support():
    r = _make_run(support=0.3, recall=0.9, findings=8)
    assert _is_passing(r) is False


def test_is_passing_blocks_low_recall_synthetic():
    r = _make_run(support=0.9, recall=0.1, findings=8)
    assert _is_passing(r) is False


def test_is_passing_blocks_too_few_findings():
    r = _make_run(support=1.0, recall=1.0, findings=1)
    assert _is_passing(r) is False


def test_is_passing_real_task_no_recall_required():
    r = _make_run(support=0.8, recall=None, findings=5)
    assert _is_passing(r) is True


def test_is_passing_real_task_low_support_fails():
    r = _make_run(support=0.4, recall=None, findings=5)
    assert _is_passing(r) is False


def test_render_pass_k_markdown_marks_pass_and_fail():
    runs = [
        _make_run(support=0.9, recall=0.7, findings=8),
        _make_run(support=0.9, recall=0.7, findings=8),
        _make_run(support=0.2, recall=0.0, findings=2),  # fail
        _make_run(support=0.9, recall=0.7, findings=8),
    ]
    p = PassKResult(
        task_id="syn-x",
        kind="synthetic",
        query="x",
        k=4,
        runs=runs,
        n_passing=3,
        pass_k=False,
    )
    report = PassKReport(
        started_at="2026-04-30T10:00:00",
        finished_at="2026-04-30T10:30:00",
        n_tasks=1,
        k=4,
        pass_k_rate=0.0,
        avg_run_pass_rate=0.75,
        results=[p],
    )
    md = render_pass_k_markdown(report)
    assert "Pass^4 rate: 0.00%" in md
    assert "Per-run pass rate: 75.00%" in md
    assert "✓" in md  # passing runs
    assert "✗" in md  # failing run
    assert "syn-x" in md
