"""Redis response cache — optional when Redis is down if redis_optional is True."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RedisCache:
    def __init__(self, client: Redis | None, *, optional: bool) -> None:
        self._client = client
        self._optional = optional

    @property
    def client(self) -> Redis | None:
        return self._client

    def build_cache_key(self, normalized_task: str, model_hint: str = "") -> str:
        digest = hashlib.sha256(f"{normalized_task}\n{model_hint}".encode()).hexdigest()
        return f"cache:task:v1:{digest}"

    async def get_cached_response(self, cache_key: str) -> dict[str, Any] | None:
        if not self._client:
            return None
        try:
            raw = await self._client.get(cache_key)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode()
            return json.loads(raw)
        except Exception:
            logger.warning("Redis GET failed", exc_info=True)
            if not self._optional:
                raise
            return None

    async def set_cached_response(self, cache_key: str, payload: dict[str, Any], ttl: int) -> None:
        if not self._client:
            return
        try:
            await self._client.setex(cache_key, ttl, json.dumps(payload))
        except Exception:
            logger.warning("Redis SET failed", exc_info=True)
            if not self._optional:
                raise

    async def ping(self) -> bool:
        if not self._client:
            return False
        try:
            return bool(await self._client.ping())
        except Exception:
            return False
