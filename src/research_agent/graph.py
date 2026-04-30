"""LangGraph wiring: plan → search → rank → read → synthesize → verify ⇄ synthesize → END.

The ``verify → synthesize`` back-edge is the self-correction loop. After each
synthesize attempt the verifier scores claim grounding; if support rate drops
below ``VERIFY_SUPPORT_THRESHOLD`` and we haven't exceeded ``MAX_SYNTHESIZE_ATTEMPTS``,
we go back to synthesize with the verifier's feedback in state.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph

from research_agent.nodes.plan import plan_node
from research_agent.nodes.rank import rank_node
from research_agent.nodes.read import read_node
from research_agent.nodes.search import search_node
from research_agent.nodes.synthesize import synthesize_node
from research_agent.nodes.verify import verify_node
from research_agent.state import ResearchState

VERIFY_SUPPORT_THRESHOLD = 0.7
MAX_SYNTHESIZE_ATTEMPTS = 2  # one initial attempt + one retry


def _after_verify(state: ResearchState) -> str:
    """Conditional edge: retry synthesize on low support, otherwise finish."""
    rate = state.get("verify_support_rate", 1.0)
    attempts = state.get("synthesize_attempts", 0)
    if rate < VERIFY_SUPPORT_THRESHOLD and attempts < MAX_SYNTHESIZE_ATTEMPTS:
        return "synthesize"
    return "END"


@lru_cache(maxsize=1)
def build_graph():
    builder = StateGraph(ResearchState)
    builder.add_node("plan", plan_node)
    builder.add_node("search", search_node)
    builder.add_node("rank", rank_node)
    builder.add_node("read", read_node)
    builder.add_node("synthesize", synthesize_node)
    builder.add_node("verify", verify_node)

    builder.set_entry_point("plan")
    builder.add_edge("plan", "search")
    builder.add_edge("search", "rank")
    builder.add_edge("rank", "read")
    builder.add_edge("read", "synthesize")
    builder.add_edge("synthesize", "verify")
    builder.add_conditional_edges(
        "verify",
        _after_verify,
        {"synthesize": "synthesize", "END": END},
    )

    return builder.compile()
