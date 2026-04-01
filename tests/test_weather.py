"""Tests for the weather tool — mocked LLM extraction and API call."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools.weather import WeatherAgent


@pytest.fixture()
def weather_agent():
    with patch("agent.tools.base.build_llm") as mock_build:
        mock_llm = AsyncMock()
        mock_build.return_value = mock_llm
        agent = WeatherAgent()
        agent.llm = mock_llm
        yield agent


def _make_aiohttp_mock(json_data):
    """Build nested async context-manager mocks for aiohttp."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


@pytest.mark.asyncio
async def test_tool_executer_returns_schema(weather_agent):
    """_tool_executer should return all required output fields (WeatherAPI path)."""
    json_data = {
        "current": {
            "temp_c": 22.0,
            "temp_f": 71.6,
            "condition": {"text": "Partly cloudy"},
        },
        "location": {"name": "London"},
    }
    mock_session = _make_aiohttp_mock(json_data)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await weather_agent._tool_executer({"city": "London"})

    assert result["temp_c"] == 22.0
    assert result["temp_f"] == 71.6
    assert result["condition"] == "Partly cloudy"
    assert result["city_name"] == "London"


@pytest.mark.asyncio
async def test_tool_executer_default_city(weather_agent):
    """Missing city param should default to London."""
    json_data = {
        "current": {
            "temp_c": 15,
            "temp_f": 59,
            "condition": {"text": "Rain"},
        },
        "location": {"name": "London"},
    }
    mock_session = _make_aiohttp_mock(json_data)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await weather_agent._tool_executer({})

    assert result["city_name"] == "London"
