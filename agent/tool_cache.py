"""Tool-level TTL cache and LangChain LLM response cache initialization."""

from __future__ import annotations

import json
import os
from hashlib import md5
from time import time
from typing import Any, Awaitable, Callable

from agent.yaml_config import load_config

_cache: dict[str, tuple[Any, float]] = {}


async def cached_call(
    fn: Callable[..., Awaitable[Any]],
    name: str,
    ttl: int,
    **kwargs: Any,
) -> Any:
    """Execute *fn* with TTL-based caching keyed on (name + kwargs).

    If ttl == 0, bypass caching entirely (e.g. calculator — deterministic).
    """
    if ttl == 0:
        return await fn(**kwargs)

    key = md5(f"{name}:{json.dumps(kwargs, sort_keys=True)}".encode()).hexdigest()
    if key in _cache:
        val, exp = _cache[key]
        if time() < exp:
            return val

    result = await fn(**kwargs)
    _cache[key] = (result, time() + ttl)
    return result


def init_llm_cache() -> None:
    """Set up LangChain's SQLiteCache for LLM response caching."""
    cfg = load_config()
    cache_cfg = cfg.get("cache", {})

    if not cache_cfg.get("enabled", False):
        return

    db_path = cache_cfg.get("llm_cache_path", "./.cache/langchain.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    from langchain_community.cache import SQLiteCache
    from langchain_core.globals import set_llm_cache

    set_llm_cache(SQLiteCache(database_path=db_path))
