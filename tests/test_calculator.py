"""Tests for the calculator tool — safe math evaluation and _tool_executor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools.base import ToolInvocation, UserFacingToolError
from agent.tools.calculator import _normalize_expression, _safe_eval


class TestSafeEval:
    def test_basic_addition(self):
        assert _safe_eval("2 + 3") == 5.0

    def test_multiplication(self):
        assert _safe_eval("42 * 18") == 756.0

    def test_division(self):
        assert _safe_eval("10 / 4") == 2.5

    def test_exponentiation(self):
        assert _safe_eval("2 ** 10") == 1024.0

    def test_caret_normalized_to_power(self):
        assert _safe_eval("3 ^ 2") == 9.0
        assert _safe_eval("2 ^ 3") == 8.0

    def test_cbrt(self):
        assert _safe_eval("cbrt(27)") == 3.0
        assert abs(_safe_eval("cbrt(-8)") - (-2.0)) < 1e-12

    def test_golden_school_style_expression(self):
        expr = "(sqrt(144) * (3^2 - 5)) / (2^3 + cbrt(27))"
        expected = (12.0 * (9.0 - 5.0)) / (8.0 + 3.0)
        assert abs(_safe_eval(expr) - expected) < 1e-9

    def test_normalize_expression(self):
        assert _normalize_expression("  a ^ b ") == "a ** b"

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
async def test_eval_expression_raises_user_facing_for_unsupported_function():
    from agent.tools.calculator import CalculatorAgent

    agent = CalculatorAgent()
    with pytest.raises(UserFacingToolError, match="does not support"):
        await agent._tool_executor(
            ToolInvocation.from_parts(
                task="x",
                sub_task="y",
                planner_params={"expression": "unknown_func(1)"},
            )
        )


@pytest.mark.asyncio
async def test_calculator_tool_executor():
    from agent.tools.calculator import CalculatorAgent

    agent = CalculatorAgent()
    result = await agent._tool_executor(
        ToolInvocation.from_parts(
            task="x",
            sub_task="y",
            planner_params={"expression": "2 + 2"},
        )
    )
    assert result == {"result": 4.0}


@pytest.mark.asyncio
async def test_run_eval_division_by_zero_raises_no_llm():
    """Planner supplied a valid expression that fails at eval — no tool LLM recovery."""
    from agent.tools.calculator import CalculatorAgent

    with patch("agent.tools.base.build_llm") as mock_build:
        mock_llm = AsyncMock()
        mock_build.return_value = mock_llm
        agent = CalculatorAgent()
        with pytest.raises(UserFacingToolError, match="Division by zero"):
            await agent.run(
                state={
                    "task": "compute",
                    "results": {},
                    "context_summary": "",
                },
                plan_task={"sub_task": "fix", "params": {"expression": "1/0"}},
            )
        mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_run_invalid_planner_expression_uses_tool_llm():
    """Empty expression triggers tool LLM to infer params."""
    from agent.tools.calculator import CalculatorAgent

    with patch("agent.tools.base.build_llm") as mock_build:
        mock_llm = AsyncMock()
        mock_build.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content='{"expression": "2+2"}')
        )
        agent = CalculatorAgent()
        out = await agent.run(
            state={
                "task": "compute",
                "results": {},
                "context_summary": "",
            },
            plan_task={"sub_task": "x", "params": {"expression": ""}},
        )
        assert out["result"] == 4.0
        mock_llm.ainvoke.assert_called_once()
