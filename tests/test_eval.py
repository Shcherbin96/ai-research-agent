from research_agent.eval.dataset import load_dataset
from research_agent.eval.judge import _claims_from_findings, support_rate
from research_agent.eval.judge import ClaimVerdict
from research_agent.eval.runner import _normalize, _recall, render_markdown, EvalReport, TaskResult
from research_agent.models import Brief, Citation


def test_dataset_loads_and_validates():
    ds = load_dataset()
    assert ds.version
    assert len(ds.tasks) >= 10
    kinds = {t.kind for t in ds.tasks}
    assert "synthetic" in kinds
    assert "real" in kinds
    ids = {t.id for t in ds.tasks}
    assert len(ids) == len(ds.tasks), "task IDs must be unique"


def test_claims_from_findings_strips_markers():
    findings = [
        "Mem0 introduces graph-augmented memory [1]",
        "Vector retrieval still wins on cost [2][3]",
        "ungrounded line",
    ]
    out = _claims_from_findings(findings)
    assert out[0][0] == "Mem0 introduces graph-augmented memory"
    assert out[0][1] == [1]
    assert out[1][1] == [2, 3]
    assert out[2][1] == []


def test_support_rate_arithmetic():
    verdicts = [
        ClaimVerdict(claim="a", citation_indices=[1], verdict="supported"),
        ClaimVerdict(claim="b", citation_indices=[2], verdict="unsupported"),
        ClaimVerdict(claim="c", citation_indices=[3], verdict="supported"),
        ClaimVerdict(claim="d", citation_indices=[], verdict="no_citation"),
    ]
    assert abs(support_rate(verdicts) - 0.5) < 1e-9


def test_normalize_url():
    assert _normalize("HTTP://Arxiv.org/abs/X/") == "https://arxiv.org/abs/x"


def test_recall_matches_cited_url():
    brief = Brief(
        query="x",
        executive_summary="s",
        citations=[
            Citation(index=1, candidate_url="https://arxiv.org/abs/2504.19413", title="Mem0"),
        ],
    )
    rate, matched, missed = _recall(["https://arxiv.org/abs/2504.19413"], brief)
    assert rate == 1.0
    assert matched and not missed


def test_recall_handles_missed_url():
    brief = Brief(
        query="x",
        executive_summary="s",
        citations=[Citation(index=1, candidate_url="https://example.com", title="X")],
    )
    rate, matched, missed = _recall(
        ["https://arxiv.org/abs/2504.19413", "https://github.com/mem0ai/mem0"], brief
    )
    assert rate == 0.0
    assert not matched
    assert len(missed) == 2


def test_render_markdown_table():
    report = EvalReport(
        started_at="2026-04-29T23:00:00",
        finished_at="2026-04-29T23:05:00",
        n_tasks=2,
        avg_support_rate=0.75,
        avg_recall=0.5,
        results=[
            TaskResult(
                task_id="syn-x",
                kind="synthetic",
                query="x",
                duration_sec=120,
                n_candidates=50,
                n_selected=10,
                n_facts=8,
                n_findings=6,
                n_citations=5,
                support_rate=1.0,
                recall=1.0,
            ),
            TaskResult(
                task_id="real-y",
                kind="real",
                query="y",
                duration_sec=130,
                n_candidates=40,
                n_selected=10,
                n_facts=7,
                n_findings=5,
                n_citations=4,
                support_rate=0.5,
                recall=None,
            ),
        ],
    )
    md = render_markdown(report)
    assert "Avg support rate: 75.00%" in md
    assert "Avg recall (synthetic): 50.00%" in md
    assert "syn-x" in md and "real-y" in md
    assert "—" in md  # recall placeholder for real task
