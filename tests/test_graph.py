"""End-to-end integration tests for the agent graph (>=5 assertions)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_llm_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    return msg


@pytest.fixture()
def mock_llm_factory():
    """Patch build_llm to return controllable AsyncMock LLMs per agent name."""
    llms = {}

    def _build(name: str):
        if name not in llms:
            llms[name] = AsyncMock()
        return llms[name]

    with patch("agent.graph_nodes.build_llm", side_effect=_build):
        yield llms


@pytest.mark.asyncio
async def test_calculator_basic_flow(mock_llm_factory):
    """Single calculator task: planner -> executor -> response."""
    from agent.graph_nodes import executor_node, planner_node, response_node

    plan = {"tasks": [{"id": "t1", "agent": "calculator", "type": "function", "params": {"expression": "6 * 7"}, "depends_on": []}]}
    mock_llm_factory["planner"] = AsyncMock()
    mock_llm_factory["planner"].ainvoke = AsyncMock(return_value=_mock_llm_response(json.dumps(plan)))
    mock_llm_factory["responder"] = AsyncMock()
    mock_llm_factory["responder"].ainvoke = AsyncMock(return_value=_mock_llm_response("The answer is 42."))

    state = {
        "task": "What is 6 times 7?",
        "context_summary": "",
        "plan": [],
        "results": {},
        "trace": [],
        "response": "",
        "retry_count": 0,
        "error_context": "",
        "failure_flag": False,
    }

    planner_out = await planner_node(state)
    assert len(planner_out["plan"]) == 1
    assert planner_out["plan"][0]["agent"] == "calculator"

    state["plan"] = planner_out["plan"]
    exec_out = await executor_node(state)
    assert "t1" in exec_out["results"]
    assert exec_out["results"]["t1"]["result"] == 42.0

    state["results"] = exec_out["results"]
    state["trace"] = exec_out["trace"]
    resp_out = await response_node(state)
    assert "42" in resp_out["response"]


@pytest.mark.asyncio
async def test_parallel_tasks_in_plan(mock_llm_factory):
    """Two independent tasks should both be ready in the same wave."""
    from agent.graph_nodes import executor_node

    plan = [
        {"id": "t1", "agent": "calculator", "type": "function", "params": {"expression": "2+2"}, "depends_on": []},
        {"id": "t2", "agent": "calculator", "type": "function", "params": {"expression": "3+3"}, "depends_on": []},
    ]

    state = {"task": "compute", "plan": plan, "results": {}, "trace": [], "retry_count": 0, "error_context": "", "failure_flag": False}
    out = await executor_node(state)

    assert "t1" in out["results"]
    assert "t2" in out["results"]
    assert out["results"]["t1"]["result"] == 4.0
    assert out["results"]["t2"]["result"] == 6.0


@pytest.mark.asyncio
async def test_sequential_dependency(mock_llm_factory):
    """t2 depends on t1, so only t1 runs in the first wave."""
    from agent.graph_nodes import executor_node

    plan = [
        {"id": "t1", "agent": "calculator", "type": "function", "params": {"expression": "10+5"}, "depends_on": []},
        {"id": "t2", "agent": "calculator", "type": "function", "params": {"expression": "15*2"}, "depends_on": ["t1"]},
    ]

    state = {"task": "chain", "plan": plan, "results": {}, "trace": [], "retry_count": 0, "error_context": "", "failure_flag": False}

    wave1 = await executor_node(state)
    assert "t1" in wave1["results"]
    assert "t2" not in wave1["results"]

    state["results"] = wave1["results"]
    wave2 = await executor_node(state)
    assert "t2" in wave2["results"]
    assert wave2["results"]["t2"]["result"] == 30.0


@pytest.mark.asyncio
async def test_error_sets_retry_context(mock_llm_factory):
    """A failing tool should set error_context and retry_count."""
    from agent.graph_nodes import executor_node, route_after_executor

    plan = [{"id": "t1", "agent": "calculator", "type": "function", "params": {"expression": "1/0"}, "depends_on": []}]
    state = {"task": "bad math", "plan": plan, "results": {}, "trace": [], "retry_count": 0, "error_context": "", "failure_flag": False}

    out = await executor_node(state)
    assert out["error_context"] != ""
    assert out["retry_count"] == 1

    state.update(out)
    route = route_after_executor(state)
    assert route == "retry"


@pytest.mark.asyncio
async def test_route_done_when_all_complete(mock_llm_factory):
    """Route should return 'done' when all plan tasks are in results."""
    from agent.graph_nodes import route_after_executor

    state = {
        "plan": [{"id": "t1", "agent": "calculator", "type": "function", "params": {}, "depends_on": []}],
        "results": {"t1": {"result": 1}},
        "error_context": "",
        "retry_count": 0,
    }
    assert route_after_executor(state) == "done"


@pytest.mark.asyncio
async def test_failure_flag_on_max_retries(mock_llm_factory):
    """After max retries, route should return 'fail'."""
    from agent.graph_nodes import mark_failure_node, route_after_executor

    state = {"plan": [], "results": {}, "error_context": "boom", "retry_count": 3, "failure_flag": False}
    route = route_after_executor(state)
    assert route == "fail"

    fail_out = await mark_failure_node(state)
    assert fail_out["failure_flag"] is True
