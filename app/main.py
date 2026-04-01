"""FastAPI application factory — lifespan, CORS, routers."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.routes.health import router as health_router
from app.api.routes.tasks import router as tasks_router
from app.cache.redis_cache import RedisCache
from app.settings import get_settings
from app.db.session import dispose_engine, init_db
from app.middleware.error_handler import register_exception_handlers
from app.observability.logging import setup_logging
from agent.startup import startup

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging()
    await init_db(settings.database_url)

    redis_client: Redis | None = None
    redis_available = False
    if settings.redis_url:
        try:
            redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
            redis_available = bool(await redis_client.ping())
        except Exception as exc:
            logger.warning("Redis connection failed: %s", exc)
            if not settings.redis_optional:
                raise
            redis_client = None

    app.state.redis_client = redis_client
    app.state.redis_cache = RedisCache(redis_client, optional=settings.redis_optional)
    app.state.redis_available = redis_available

    await startup()

    yield

    if redis_client is not None:
        await redis_client.close()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Tufin Agent API",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            o.strip() for o in settings.cors_origins.split(",") if o.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(tasks_router, prefix=settings.api_v1_prefix)
    app.include_router(health_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
