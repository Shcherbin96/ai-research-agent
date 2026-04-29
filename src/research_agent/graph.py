"""Wires the five nodes into a linear LangGraph: plan -> search -> rank -> read -> synthesize."""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph

from research_agent.nodes.plan import plan_node
from research_agent.nodes.read import read_node
from research_agent.nodes.search import search_node
from research_agent.nodes.synthesize import synthesize_node
from research_agent.nodes.rank import rank_node
from research_agent.state import ResearchState


@lru_cache(maxsize=1)
def build_graph():
    builder = StateGraph(ResearchState)
    builder.add_node("plan", plan_node)
    builder.add_node("search", search_node)
    builder.add_node("rank", rank_node)
    builder.add_node("read", read_node)
    builder.add_node("synthesize", synthesize_node)

    builder.set_entry_point("plan")
    builder.add_edge("plan", "search")
    builder.add_edge("search", "rank")
    builder.add_edge("rank", "read")
    builder.add_edge("read", "synthesize")
    builder.add_edge("synthesize", END)

    return builder.compile()
