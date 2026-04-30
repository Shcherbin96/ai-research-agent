from typing import TypedDict

from research_agent.models import Brief, Candidate, ExtractedFact


class ResearchState(TypedDict, total=False):
    query: str
    subqueries: list[str]
    candidates: list[Candidate]
    selected: list[Candidate]
    facts: list[ExtractedFact]
    brief: Brief | None
    errors: list[str]
    use_web: bool
    use_scholar: bool
    limit_per_source: int
    top_n: int

    # Self-correction loop. ``verify_support_rate`` carries the verifier's score.
    # ``synthesize_attempts`` counts how many times synthesize_node has run, so the
    # graph's conditional edge can stop after the configured retry budget.
    # ``verify_feedback`` is the human-readable feedback string that synthesize_node
    # consumes on a retry to fix unsupported claims.
    verify_support_rate: float
    verify_feedback: str
    synthesize_attempts: int
