"""Tests for the web search tool — mocked Tavily wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.tools.base import ToolInvocation
from agent.tools.web_search import WebSearchAgent


@pytest.fixture()
def search_agent():
    with patch("agent.tools.base.build_llm") as mock_build:
        mock_llm = AsyncMock()
        mock_build.return_value = mock_llm
        agent = WebSearchAgent()
        agent.llm = mock_llm
        yield agent


@pytest.mark.asyncio
async def test_tool_executor_returns_schema(search_agent):
    """_tool_executor should return query, results list, and summary."""
    mock_wrapper = AsyncMock()
    mock_wrapper.results_async = AsyncMock(return_value=[
        {"title": "Result 1", "url": "https://example.com/1", "content": "First result content"},
        {"title": "Result 2", "url": "https://example.com/2", "content": "Second result content"},
    ])

    with patch(
        "langchain_community.utilities.tavily_search.TavilySearchAPIWrapper",
        return_value=mock_wrapper,
    ):
        result = await search_agent._tool_executor(
            ToolInvocation.from_parts(planner_params={"query": "test query"})
        )

    assert result["query"] == "test query"
    assert len(result["results"]) == 2
    assert result["results"][0]["title"] == "Result 1"
    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


@pytest.mark.asyncio
async def test_empty_query_returns_no_results(search_agent):
    result = await search_agent._tool_executor(
        ToolInvocation.from_parts(planner_params={"query": ""})
    )
    assert result["results"] == []
    assert result["summary"] == "No query provided."
