"""Health — SQLite and Redis connectivity."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.cache.redis_cache import RedisCache
from app.settings import get_settings
from app.db.session import get_session_factory
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = get_settings()
    sqlite_state = "error"
    try:
        factory = get_session_factory(settings.database_url)
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            sqlite_state = "ok"
    except Exception:
        sqlite_state = "error"

    redis_state = "skipped"
    cache: RedisCache = request.app.state.redis_cache
    if settings.redis_url:
        if await cache.ping():
            redis_state = "ok"
        else:
            redis_state = "error"
    else:
        redis_state = "skipped"

    overall = "ok"
    if sqlite_state != "ok":
        overall = "degraded"
    elif redis_state == "error" and settings.redis_url and not settings.redis_optional:
        overall = "degraded"
    elif redis_state == "error" and settings.redis_url and settings.redis_optional:
        overall = "degraded"

    return HealthResponse(status=overall, sqlite=sqlite_state, redis=redis_state)
