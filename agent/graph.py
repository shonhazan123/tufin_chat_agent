"""LangGraph StateGraph compilation with conditional edges."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.graph_nodes import (
    executor_node,
    mark_failure_node,
    planner_node,
    prepare_responder_context_node,
    response_node,
    route_after_executor,
)
from agent.types.agent_state import AgentState

_compiled_execution_graph = None


def build_graph():
    """Build and compile the agent execution graph.

    Graph topology:
        START -> planner -> executor -> [route_after_executor]
            "continue" -> executor   (next wave of parallel tasks)
            "fail"     -> mark_failure -> prepare_context -> responder -> END
            "done"     -> prepare_context -> responder -> END
    """
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("mark_failure", mark_failure_node)
    graph.add_node("prepare_context", prepare_responder_context_node)
    graph.add_node("responder", response_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")

    graph.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "continue": "executor",
            "fail": "mark_failure",
            "done": "prepare_context",
        },
    )

    graph.add_edge("mark_failure", "prepare_context")
    graph.add_edge("prepare_context", "responder")
    graph.add_edge("responder", END)

    global _compiled_execution_graph
    _compiled_execution_graph = graph.compile()
    return _compiled_execution_graph


def get_graph():
    """Return the compiled graph. Raises RuntimeError if not built yet."""
    if _compiled_execution_graph is None:
        raise RuntimeError("Graph not compiled — call startup() first")
    return _compiled_execution_graph
