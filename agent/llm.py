"""LLM abstraction — sole ChatOpenAI instantiation point + semaphore management."""

from __future__ import annotations

import asyncio
from functools import lru_cache

from langchain_openai import ChatOpenAI

from agent.yaml_config import load_config

_llm_sem: asyncio.Semaphore | None = None


@lru_cache(maxsize=None)
def build_llm(agent_name: str) -> ChatOpenAI:
    """Build a ChatOpenAI instance for the named agent.

    This is the *only* place ChatOpenAI is instantiated.
    Results are cached per agent_name via @lru_cache.
    Agent names include planner, responder, and each LLM-backed tool (e.g. weather,
    web_search, calculator, unit_converter).
    """
    cfg = load_config()
    provider = cfg["provider"]
    conn = cfg[provider]
    agent_cfg = cfg["agents"][agent_name]

    kwargs: dict = {
        "base_url": conn["base_url"],
        "api_key": conn["api_key"],
        "model": agent_cfg["model"],
        "temperature": agent_cfg.get("temperature", 0),
        "max_tokens": agent_cfg.get("max_tokens", 512),
        "max_retries": agent_cfg.get("max_retries", 2),
    }

    if provider == "ollama":
        num_ctx = agent_cfg.get("num_ctx")
        if num_ctx is not None:
            # Caps KV cache / VRAM (Ollama native options; not valid as top-level chat payload).
            kwargs["extra_body"] = {"options": {"num_ctx": int(num_ctx)}}

    return ChatOpenAI(**kwargs)


def init_llm_semaphore() -> None:
    """Initialize the LLM concurrency semaphore. Call once at startup."""
    global _llm_sem
    cfg = load_config()
    limit = 1 if cfg["provider"] == "ollama" else 5
    _llm_sem = asyncio.Semaphore(limit)


def get_llm_semaphore() -> asyncio.Semaphore:
    """Return the initialized LLM semaphore.

    Raises RuntimeError if init_llm_semaphore() hasn't been called.
    """
    if _llm_sem is None:
        raise RuntimeError(
            "LLM semaphore not initialized — call init_llm_semaphore() at startup"
        )
    return _llm_sem
