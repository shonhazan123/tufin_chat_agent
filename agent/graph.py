"""LangGraph StateGraph compilation with conditional edges."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.graph_nodes import (
    executor_node,
    mark_failure_node,
    planner_node,
    response_node,
    route_after_executor,
)
from agent.state import AgentState

_compiled = None


def build_graph():
    """Build and compile the agent execution graph.

    Graph topology:
        START -> planner -> executor -> [route_after_executor]
            "continue" -> executor   (next wave of parallel tasks)
            "retry"    -> planner    (re-plan with error context)
            "fail"     -> mark_failure -> responder
            "done"     -> responder -> END
    """
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("mark_failure", mark_failure_node)
    graph.add_node("responder", response_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")

    graph.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "continue": "executor",
            "retry": "planner",
            "fail": "mark_failure",
            "done": "responder",
        },
    )

    graph.add_edge("mark_failure", "responder")
    graph.add_edge("responder", END)

    global _compiled
    _compiled = graph.compile()
    return _compiled


def get_graph():
    """Return the compiled graph. Raises RuntimeError if not built yet."""
    if _compiled is None:
        raise RuntimeError("Graph not compiled — call startup() first")
    return _compiled
