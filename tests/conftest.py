"""Shared test fixtures — mock config, mock LLM, mock aiohttp."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

_TEST_CONFIG = {
    "provider": "ollama",
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama"},
    "openai": {"base_url": "https://api.openai.com/v1", "api_key": "test"},
    "agents": {
        "planner": {"model": "test", "max_tokens": 512, "temperature": 0, "num_ctx": 4096},
        "responder": {"model": "test", "max_tokens": 1024, "temperature": 0.3, "num_ctx": 8192, "max_retries": 3},
        "weather": {"model": "test", "max_tokens": 256, "temperature": 0, "num_ctx": 2048, "max_retries": 3},
        "web_search": {"model": "test", "max_tokens": 512, "temperature": 0, "num_ctx": 4096, "max_retries": 3},
        "calculator": {"model": "test", "max_tokens": 256, "temperature": 0, "num_ctx": 2048, "max_retries": 3},
        "unit_converter": {"model": "test", "max_tokens": 256, "temperature": 0, "num_ctx": 2048, "max_retries": 3},
        "database_query": {"model": "test", "max_tokens": 512, "temperature": 0, "num_ctx": 4096, "max_retries": 3},
    },
    "tools": {
        "calculator": {"enabled": True},
        "weather": {"enabled": True, "api_key": "test-key", "timeout_seconds": 5},
        "web_search": {"enabled": True, "api_key": "test-key", "max_results": 3},
        "unit_converter": {"enabled": True, "currency_api_key": "test-key"},
        "database_query": {"enabled": True, "db_path": ":memory:", "max_rows": 50},
    },
    "cache": {
        "enabled": False,
        "llm_cache_path": "./.cache/test.db",
        "tool_ttls": {"calculator": 0, "weather": 300, "web_search": 600, "unit_converter": 60, "database_query": 0},
    },
    "executor": {
        "max_waves": 10,
        "max_parallel_tools": 8,
        "tool_timeout_seconds": 15,
    },
}

_CONFIG_PATCH_TARGETS = [
    "agent.yaml_config.load_config",
    "agent.llm.load_config",
    "agent.tool_cache.load_config",
    "agent.tools.base.load_config",
    "agent.tools.weather.load_config",
    "agent.tools.web_search.load_config",
    "agent.tools.unit_converter.load_config",
    "agent.tools.database_query.load_config",
    "agent.graph_nodes.load_config",
    "app.services.task_service.load_config",
    "app.integrations.agent_runner.load_config",
]


@pytest.fixture()
def test_config():
    return _TEST_CONFIG


def pytest_configure(config):
    """Populate the tool registry and LLM semaphore before tests (matches production startup)."""
    from agent.llm import init_llm_semaphore
    from agent.tools import discover_tools

    discover_tools()
    init_llm_semaphore()


@pytest.fixture(autouse=True)
def _patch_config():
    """Patch load_config in every module that imports it."""
    patches = [patch(t, return_value=_TEST_CONFIG) for t in _CONFIG_PATCH_TARGETS]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def mock_llm():
    """Return an AsyncMock that behaves like ChatOpenAI."""
    llm = AsyncMock()
    llm.ainvoke = AsyncMock()
    return llm
