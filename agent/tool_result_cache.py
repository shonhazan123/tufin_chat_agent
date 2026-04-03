"""Tool-level TTL cache and LangChain LLM response cache initialization."""

from __future__ import annotations

import json
import os
from hashlib import md5
from time import time
from typing import Any, Awaitable, Callable

from agent.config_loader import load_config

_ttl_cache_store: dict[str, tuple[Any, float]] = {}


async def cached_call(
    async_function: Callable[..., Awaitable[Any]],
    name: str,
    ttl: int,
    **kwargs: Any,
) -> Any:
    """Execute *async_function* with TTL-based caching keyed on (name + kwargs).

    If ttl == 0, bypass caching entirely (e.g. tools configured with ttl 0 in shared.yaml).
    """
    if ttl == 0:
        return await async_function(**kwargs)

    key = md5(f"{name}:{json.dumps(kwargs, sort_keys=True)}".encode()).hexdigest()
    if key in _ttl_cache_store:
        cached_value, expiration_timestamp = _ttl_cache_store[key]
        if time() < expiration_timestamp:
            return cached_value

    result = await async_function(**kwargs)
    _ttl_cache_store[key] = (result, time() + ttl)
    return result


def init_llm_cache() -> None:
    """Set up LangChain's SQLiteCache for LLM response caching."""
    config = load_config()
    cache_config = config.get("cache", {})

    if not cache_config.get("enabled", False):
        return

    db_path = cache_config.get("llm_cache_path", "./.cache/langchain.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    from langchain_community.cache import SQLiteCache
    from langchain_core.globals import set_llm_cache

    set_llm_cache(SQLiteCache(database_path=db_path))
