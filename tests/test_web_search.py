"""Tests for the web search tool — mocked Tavily wrapper + LLM extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools.base import ToolInvocation
from agent.tools.web_search import WebSearchAgent


def _mock_llm_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    return msg


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
    """_tool_executor should return query, answer (LLM-extracted), and sources."""
    mock_wrapper = AsyncMock()
    mock_wrapper.results_async = AsyncMock(return_value=[
        {"title": "Result 1", "url": "https://example.com/1", "content": "First result content"},
        {"title": "Result 2", "url": "https://example.com/2", "content": "Second result content"},
    ])

    search_agent.llm.ainvoke = AsyncMock(
        return_value=_mock_llm_response('{"answer": "The answer is 42."}')
    )

    with patch(
        "langchain_community.utilities.tavily_search.TavilySearchAPIWrapper",
        return_value=mock_wrapper,
    ):
        result = await search_agent._tool_executor(
            ToolInvocation.from_parts(planner_params={"query": "test query"})
        )

    assert result["query"] == "test query"
    assert isinstance(result["answer"], str)
    assert "42" in result["answer"]
    assert len(result["sources"]) == 2
    assert result["sources"][0]["title"] == "Result 1"


@pytest.mark.asyncio
async def test_empty_query_returns_no_results(search_agent):
    search_agent.llm.ainvoke = AsyncMock(
        return_value=_mock_llm_response('{"query": ""}')
    )
    result = await search_agent._tool_executor(
        ToolInvocation.from_parts(planner_params={"query": ""})
    )
    assert result["sources"] == []
    assert result["answer"] == "No query provided."
