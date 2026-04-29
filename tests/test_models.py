from research_agent.models import Brief, Candidate, Citation, ExtractedFact


def test_candidate_minimal_roundtrip():
    c = Candidate(
        source="arxiv",
        url="https://arxiv.org/abs/2401.00001",
        title="Some Paper",
        snippet="abstract text",
    )
    dumped = c.model_dump(mode="json")
    restored = Candidate.model_validate(dumped)
    assert restored.source == "arxiv"
    assert restored.title == "Some Paper"
    assert restored.authors == []


def test_extracted_fact_quotes_optional():
    f = ExtractedFact(
        candidate_url="https://example.com/x",
        thesis="X improves Y by Z%.",
    )
    assert f.methods == []
    assert f.quotes == []


def test_brief_with_citations():
    b = Brief(
        query="test query",
        executive_summary="summary [1]",
        key_findings=["finding one [1]"],
        citations=[
            Citation(
                index=1,
                candidate_url="https://example.com/x",
                title="X",
                quote="exact quote",
            )
        ],
    )
    dumped = b.model_dump(mode="json")
    restored = Brief.model_validate(dumped)
    assert restored.citations[0].index == 1
    assert restored.citations[0].quote == "exact quote"


def test_brief_defaults_empty():
    b = Brief(query="q", executive_summary="s")
    assert b.key_findings == []
    assert b.comparison_matrix == []
    assert b.open_questions == []
    assert b.citations == []
