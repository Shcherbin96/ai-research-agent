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
