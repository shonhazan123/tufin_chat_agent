"""Tests for the unit converter tool — _tool_executer conversion paths."""

from __future__ import annotations

import pytest

from agent.tools.unit_converter import UnitConverterAgent


@pytest.fixture()
def converter():
    return UnitConverterAgent()


@pytest.mark.asyncio
async def test_km_to_miles(converter):
    result = await converter._tool_executer({"value": 10, "from_unit": "km", "to_unit": "miles"})
    assert abs(result["result"] - 6.2137) < 0.01
    assert result["from_unit"] == "km"
    assert result["to_unit"] == "miles"
    assert "formula" in result


@pytest.mark.asyncio
async def test_celsius_to_fahrenheit(converter):
    result = await converter._tool_executer({"value": 100, "from_unit": "celsius", "to_unit": "fahrenheit"})
    assert abs(result["result"] - 212.0) < 0.01


@pytest.mark.asyncio
async def test_kg_to_lb(converter):
    result = await converter._tool_executer({"value": 1, "from_unit": "kg", "to_unit": "lb"})
    assert abs(result["result"] - 2.2046) < 0.01


@pytest.mark.asyncio
async def test_same_unit_identity(converter):
    result = await converter._tool_executer({"value": 42, "from_unit": "km", "to_unit": "km"})
    assert result["result"] == 42
    assert result["formula"] == "identity (same unit)"


@pytest.mark.asyncio
async def test_fahrenheit_to_kelvin(converter):
    result = await converter._tool_executer({"value": 32, "from_unit": "fahrenheit", "to_unit": "kelvin"})
    assert abs(result["result"] - 273.15) < 0.01


@pytest.mark.asyncio
async def test_unsupported_conversion_raises(converter):
    with pytest.raises(ValueError, match="Unsupported conversion"):
        await converter._tool_executer({"value": 1, "from_unit": "km", "to_unit": "kg"})
