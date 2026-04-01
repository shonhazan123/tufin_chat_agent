"""Tests for the calculator tool — safe math evaluation and _tool_executer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools.calculator import _safe_eval


class TestSafeEval:
    def test_basic_addition(self):
        assert _safe_eval("2 + 3") == 5.0

    def test_multiplication(self):
        assert _safe_eval("42 * 18") == 756.0

    def test_division(self):
        assert _safe_eval("10 / 4") == 2.5

    def test_exponentiation(self):
        assert _safe_eval("2 ** 10") == 1024.0

    def test_nested_expression(self):
        assert _safe_eval("(3 + 4) * 2") == 14.0

    def test_sqrt_function(self):
        assert _safe_eval("sqrt(144)") == 12.0

    def test_pi_constant(self):
        result = _safe_eval("pi")
        assert abs(result - 3.14159265) < 0.001

    def test_negative_number(self):
        assert _safe_eval("-5 + 3") == -2.0

    def test_division_by_zero_raises(self):
        with pytest.raises(ZeroDivisionError):
            _safe_eval("1 / 0")

    def test_unsupported_name_raises(self):
        with pytest.raises(ValueError, match="Unsupported function"):
            _safe_eval("__import__('os')")

    def test_unsupported_function_raises(self):
        with pytest.raises(ValueError, match="Unsupported function"):
            _safe_eval("eval('1')")


@pytest.mark.asyncio
async def test_calculator_tool_executer():
    from agent.tools.calculator import CalculatorAgent

    agent = CalculatorAgent()
    result = await agent._tool_executer({"expression": "2 + 2"})
    assert result == {"result": 4.0}


@pytest.mark.asyncio
async def test_run_planner_args_fail_then_tool_llm_recover():
    """Bad planner expression triggers tool LLM; second attempt succeeds."""
    from agent.tools.calculator import CalculatorAgent

    with patch("agent.tools.base.build_llm") as mock_build:
        mock_llm = AsyncMock()
        mock_build.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content='{"expression": "2+2"}')
        )
        agent = CalculatorAgent()
        out = await agent.run(
            user_msg="compute",
            sub_task="fix",
            prior_results={},
            planner_params={"expression": "1/0"},
            context_summary="",
        )
        assert out["result"] == 4.0
        mock_llm.ainvoke.assert_called_once()
