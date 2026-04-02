"""Tests for the unit converter tool — _tool_executor conversion paths."""

from __future__ import annotations

import pytest

from agent.tools.base import ToolInvocation
from agent.tools.unit_converter import UnitConverterAgent


def _exec(agent: UnitConverterAgent, planner_params: dict) -> object:
    return agent._tool_executor(
        ToolInvocation.from_parts(planner_params=planner_params)
    )


@pytest.fixture()
def converter():
    return UnitConverterAgent()


@pytest.mark.asyncio
async def test_km_to_miles(converter):
    result = await _exec(converter, {"value": 10, "from_unit": "km", "to_unit": "miles"})
    assert abs(result["result"] - 6.2137) < 0.01
    assert result["from_unit"] == "km"
    assert result["to_unit"] == "miles"
    assert "formula" in result


@pytest.mark.asyncio
async def test_celsius_to_fahrenheit(converter):
    result = await _exec(converter, {"value": 100, "from_unit": "celsius", "to_unit": "fahrenheit"})
    assert abs(result["result"] - 212.0) < 0.01


@pytest.mark.asyncio
async def test_kg_to_lb(converter):
    result = await _exec(converter, {"value": 1, "from_unit": "kg", "to_unit": "lb"})
    assert abs(result["result"] - 2.2046) < 0.01


@pytest.mark.asyncio
async def test_same_unit_identity(converter):
    result = await _exec(converter, {"value": 42, "from_unit": "km", "to_unit": "km"})
    assert result["result"] == 42
    assert result["formula"] == "identity (same unit)"


@pytest.mark.asyncio
async def test_fahrenheit_to_kelvin(converter):
    result = await _exec(converter, {"value": 32, "from_unit": "fahrenheit", "to_unit": "kelvin"})
    assert abs(result["result"] - 273.15) < 0.01


@pytest.mark.asyncio
async def test_unsupported_conversion_raises(converter):
    """Invalid pair from planner raises; no tool LLM (params were present)."""
    with pytest.raises(ValueError, match="Unsupported conversion"):
        await _exec(converter, {"value": 1, "from_unit": "km", "to_unit": "kg"})
