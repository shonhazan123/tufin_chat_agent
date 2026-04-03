"""LLM abstraction — sole ChatOpenAI instantiation point + concurrency semaphore management."""

from __future__ import annotations

import asyncio
from functools import lru_cache

from langchain_openai import ChatOpenAI

from agent.config_loader import load_config

_llm_concurrency_semaphore: asyncio.Semaphore | None = None


@lru_cache(maxsize=None)
def build_llm(agent_name: str) -> ChatOpenAI:
    """Build a ChatOpenAI instance for the named agent.

    This is the *only* place ChatOpenAI is instantiated.
    Results are cached per agent_name via @lru_cache.
    Agent names include planner, responder, and each LLM-backed tool (e.g. weather,
    web_search, calculator, unit_converter).
    """
    config = load_config()
    provider = config["provider"]
    provider_connection = config[provider]
    agent_config = config["agents"][agent_name]

    kwargs: dict = {
        "base_url": provider_connection["base_url"],
        "api_key": provider_connection["api_key"],
        "model": agent_config["model"],
        "temperature": agent_config.get("temperature", 0),
        "max_tokens": agent_config.get("max_tokens", 512),
        "max_retries": agent_config.get("max_retries", 2),
    }

    if provider == "ollama":
        num_ctx = agent_config.get("num_ctx")
        if num_ctx is not None:
            # Caps KV cache / VRAM (Ollama native options; not valid as top-level chat payload).
            kwargs["extra_body"] = {"options": {"num_ctx": int(num_ctx)}}

    return ChatOpenAI(**kwargs)


def init_llm_semaphore() -> None:
    """Initialize the LLM concurrency semaphore. Call once at startup."""
    global _llm_concurrency_semaphore
    config = load_config()
    limit = 1 if config["provider"] == "ollama" else 5
    _llm_concurrency_semaphore = asyncio.Semaphore(limit)


def get_llm_semaphore() -> asyncio.Semaphore:
    """Return the initialized LLM semaphore.

    Raises RuntimeError if init_llm_semaphore() hasn't been called.
    """
    if _llm_concurrency_semaphore is None:
        raise RuntimeError(
            "LLM semaphore not initialized — call init_llm_semaphore() at startup"
        )
    return _llm_concurrency_semaphore
