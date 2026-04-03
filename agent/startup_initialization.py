"""Ordered startup sequence — enforces correct initialization order.

Import order matters: config_loader -> tools autodiscovery -> llm_system_prompts ->
llm_provider_factory -> tool_result_cache -> graph.

Provider selection is fixed at process startup: set LLM_PROVIDER in .env to ``openai`` (default)
or ``ollama``. See ``config/shared.yaml`` and ``config/openai.yaml`` / ``config/ollama.yaml``.
"""

from __future__ import annotations

import logging
import os

from agent.config_loader import load_config

logger = logging.getLogger(__name__)

_REQUIRED_ENV = {
    "openai": ["OPENAI_API_KEY"],
}


def validate_config() -> None:
    """Check provider value, required env vars, and agent configs."""
    config = load_config()
    provider = config.get("provider")
    if provider not in ("ollama", "openai"):
        raise ValueError(f"provider must be 'ollama' or 'openai', got '{provider}'")

    for var in _REQUIRED_ENV.get(provider, []):
        if not os.environ.get(var):
            raise EnvironmentError(f"Missing required env var for {provider}: {var}")

    required_agents = {"planner", "responder"}
    configured = set(config.get("agents", {}).keys())
    missing = required_agents - configured
    if missing:
        raise ValueError(f"Missing agent configs: {missing}")

    logger.info("Config validated: provider=%s", provider)


async def startup() -> None:
    """Run the full initialization sequence in correct order.

    1. Validate configuration
    2. Discover and register all tools
    3. Build planner system prompt from populated registry
    4. Initialize LLM semaphore
    5. Initialize LLM response cache
    6. Compile the LangGraph execution graph
    """
    validate_config()

    from agent.tools import discover_tools
    discover_tools()

    from agent.llm_system_prompts import build_planner_prompt
    prompt = build_planner_prompt()
    logger.info("Planner prompt built (%d chars)", len(prompt))

    from agent.llm_provider_factory import init_llm_semaphore
    init_llm_semaphore()

    from agent.tool_result_cache import init_llm_cache
    init_llm_cache()

    from agent.graph import build_graph
    build_graph()

    logger.info("Startup sequence complete")
