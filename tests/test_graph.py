"""End-to-end integration tests for the agent graph (>=5 assertions)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_llm_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    return msg


def _graph_state(**kwargs):
    """Minimal AgentState-shaped dict for graph node tests."""
    defaults = {
        "task": "",
        "context_summary": "",
        "user_key_facts": "",
        "recent_messages_text": "",
        "plan": [],
        "results": {},
        "trace": [],
        "response": "",
        "error_context": "",
        "user_facing_error": "",
        "failure_flag": False,
    }
    defaults.update(kwargs)
    return defaults


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


def _ensure_calculator_mock():
    """Register tools and attach a mock LLM to the calculator agent (graph tests)."""
    from agent.tools import discover_tools
    from agent.tools.base import registry

    discover_tools()
    calc = registry.get("calculator")
    mock_llm = AsyncMock()
    calc.llm = mock_llm
    return mock_llm


@pytest.mark.asyncio
async def test_calculator_basic_flow(mock_llm_factory):
    """Single calculator task: planner -> executor -> response."""
    from agent.graph_nodes import executor_node, planner_node, response_node

    plan = {
        "tasks": [
            {
                "id": "t1",
                "agent": "calculator",
                "type": "llm",
                "sub_task": "Compute 6 times 7",
                "params": {"expression": "6 * 7"},
                "depends_on": [],
            }
        ]
    }
    mock_llm_factory["planner"] = AsyncMock()
    mock_llm_factory["planner"].ainvoke = AsyncMock(return_value=_mock_llm_response(json.dumps(plan)))
    mock_llm_factory["responder"] = AsyncMock()
    mock_llm_factory["responder"].ainvoke = AsyncMock(return_value=_mock_llm_response("The answer is 42."))

    _ensure_calculator_mock()

    state = _graph_state(
        task="What is 6 times 7?",
    )

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
        {
            "id": "t1",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Compute 2+2",
            "params": {"expression": "2+2"},
            "depends_on": [],
        },
        {
            "id": "t2",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Compute 3+3",
            "params": {"expression": "3+3"},
            "depends_on": [],
        },
    ]

    state = _graph_state(task="compute", plan=plan)

    _ensure_calculator_mock()

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
        {
            "id": "t1",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Compute 10+5",
            "params": {"expression": "10+5"},
            "depends_on": [],
        },
        {
            "id": "t2",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Evaluate 15*2",
            "params": {"expression": "15*2"},
            "depends_on": ["t1"],
        },
    ]

    state = _graph_state(task="chain", plan=plan)

    calc_llm = _ensure_calculator_mock()

    wave1 = await executor_node(state)
    assert "t1" in wave1["results"]
    assert "t2" not in wave1["results"]

    state["results"] = wave1["results"]
    calc_llm.ainvoke = AsyncMock(
        return_value=_mock_llm_response('{"expression": "15*2"}')
    )
    wave2 = await executor_node(state)
    assert "t2" in wave2["results"]
    assert wave2["results"]["t2"]["result"] == 30.0


@pytest.mark.asyncio
async def test_error_routes_to_fail_not_planner(mock_llm_factory):
    """A failing tool should set error_context; router goes to fail (no re-plan)."""
    from agent.graph_nodes import executor_node, route_after_executor

    plan = [
        {
            "id": "t1",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "divide by zero",
            "params": {"expression": "1/0"},
            "depends_on": [],
        }
    ]
    state = _graph_state(task="bad math", plan=plan)

    calc_llm = _ensure_calculator_mock()
    calc_llm.ainvoke = AsyncMock(return_value=_mock_llm_response('{"expression": "1/0"}'))

    out = await executor_node(state)
    assert out["error_context"] != ""

    state.update(out)
    route = route_after_executor(state)
    assert route == "fail"


@pytest.mark.asyncio
async def test_route_done_when_all_complete(mock_llm_factory):
    """Route should return 'done' when all plan tasks are in results."""
    from agent.graph_nodes import route_after_executor

    state = {
        "plan": [{"id": "t1", "agent": "calculator", "type": "llm", "sub_task": "noop", "depends_on": []}],
        "results": {"t1": {"result": 1}},
        "error_context": "",
    }
    assert route_after_executor(state) == "done"


@pytest.mark.asyncio
async def test_route_done_when_empty_plan(mock_llm_factory):
    """No planner tasks (e.g. greeting): executor adds nothing; route goes to responder."""
    from agent.graph_nodes import executor_node, route_after_executor

    state = _graph_state(task="hi")
    exec_out = await executor_node(state)
    assert exec_out == {}
    state.update(exec_out)
    assert route_after_executor(state) == "done"


@pytest.mark.asyncio
async def test_response_node_without_tools(mock_llm_factory):
    """Responder runs with empty results for conversational turns."""
    from agent.graph_nodes import build_llm, response_node

    build_llm("responder")
    mock_llm_factory["responder"].ainvoke = AsyncMock(
        return_value=_mock_llm_response("Hello! How can I help you today?")
    )

    summary = "Earlier: user asked about the weather."
    state = _graph_state(
        task="hi",
        context_summary=summary,
        user_key_facts="User prefers Celsius.",
    )

    out = await response_node(state)
    assert "Hello" in out["response"]
    call = mock_llm_factory["responder"].ainvoke.call_args
    messages = call[0][0]
    human = messages[1]
    assert "hi" in human.content
    assert "Conversation summary" in human.content
    assert "Earlier" in human.content
    assert "User key facts" in human.content


@pytest.mark.asyncio
async def test_failure_flag_on_executor_error(mock_llm_factory):
    """Any executor error_context routes to fail and mark_failure sets failure_flag."""
    from agent.graph_nodes import mark_failure_node, route_after_executor

    state = {"plan": [], "results": {}, "error_context": "boom", "failure_flag": False}
    route = route_after_executor(state)
    assert route == "fail"

    fail_out = await mark_failure_node(state)
    assert fail_out["failure_flag"] is True


# ---------------------------------------------------------------------------
# Dependent task param resolution tests
# ---------------------------------------------------------------------------

def test_prior_results_scoped_to_depends_on():
    """ToolInvocation.prior_results only returns results for depends_on ids."""
    from agent.tools.base import ToolInvocation

    inv = ToolInvocation(
        state={"results": {"t1": {"result": 42}, "t2": {"result": 99}}},
        plan_task={"depends_on": ["t1"], "params": {}},
    )
    assert inv.prior_results == {"t1": {"result": 42}}
    assert "t2" not in inv.prior_results


def test_prior_results_empty_when_no_depends():
    """ToolInvocation.prior_results is empty when depends_on is []."""
    from agent.tools.base import ToolInvocation

    inv = ToolInvocation(
        state={"results": {"t1": {"result": 42}}},
        plan_task={"depends_on": [], "params": {}},
    )
    assert inv.prior_results == {}


def test_from_parts_with_depends_on():
    """from_parts accepts depends_on and scopes prior_results correctly."""
    from agent.tools.base import ToolInvocation

    inv = ToolInvocation.from_parts(
        task="test",
        sub_task="use t1 output",
        prior_results={"t1": {"result": 10}, "t2": {"result": 20}},
        depends_on=["t1"],
        planner_params={"value": "placeholder"},
    )
    assert inv.prior_results == {"t1": {"result": 10}}
    assert inv.planner_params == {"value": "placeholder"}


@pytest.mark.asyncio
async def test_dependent_task_invalid_params_triggers_tool_llm(mock_llm_factory):
    """When t2 depends on t1 and has invalid params, the tool LLM is invoked to extract them."""
    from agent.graph_nodes import executor_node

    plan = [
        {
            "id": "t1",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Compute 10+5",
            "params": {"expression": "10+5"},
            "depends_on": [],
        },
        {
            "id": "t2",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Multiply previous result by 3",
            "params": {},
            "depends_on": ["t1"],
        },
    ]

    state = _graph_state(task="chain computation", plan=plan)

    calc_llm = _ensure_calculator_mock()

    wave1 = await executor_node(state)
    assert "t1" in wave1["results"]
    assert wave1["results"]["t1"]["result"] == 15.0

    state["results"] = wave1["results"]
    calc_llm.ainvoke = AsyncMock(
        return_value=_mock_llm_response('{"expression": "15 * 3"}')
    )

    wave2 = await executor_node(state)
    assert "t2" in wave2["results"]
    assert wave2["results"]["t2"]["result"] == 45.0
    calc_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_dependent_task_always_calls_tool_llm(mock_llm_factory):
    """When t2 depends on t1, the tool LLM is ALWAYS invoked to extract params from prior results."""
    from agent.graph_nodes import executor_node

    plan = [
        {
            "id": "t1",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Compute 5+5",
            "params": {"expression": "5+5"},
            "depends_on": [],
        },
        {
            "id": "t2",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Multiply by 2",
            "params": {"expression": "10 * 2"},
            "depends_on": ["t1"],
        },
    ]

    state = _graph_state(task="chain with valid params", plan=plan)

    calc_llm = _ensure_calculator_mock()

    wave1 = await executor_node(state)
    assert "t1" in wave1["results"]

    state["results"] = wave1["results"]
    calc_llm.ainvoke = AsyncMock(
        return_value=_mock_llm_response('{"expression": "10 * 2"}')
    )

    wave2 = await executor_node(state)
    assert "t2" in wave2["results"]
    assert wave2["results"]["t2"]["result"] == 20.0
    calc_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_independent_task_valid_params_skips_tool_llm(mock_llm_factory):
    """When a task has no dependencies and valid params, the tool LLM is NOT invoked."""
    from agent.graph_nodes import executor_node

    plan = [
        {
            "id": "t1",
            "agent": "calculator",
            "type": "llm",
            "sub_task": "Compute 10 * 2",
            "params": {"expression": "10 * 2"},
            "depends_on": [],
        },
    ]

    state = _graph_state(task="simple calc", plan=plan)

    calc_llm = _ensure_calculator_mock()
    calc_llm.ainvoke = AsyncMock()

    out = await executor_node(state)
    assert "t1" in out["results"]
    assert out["results"]["t1"]["result"] == 20.0
    calc_llm.ainvoke.assert_not_called()
