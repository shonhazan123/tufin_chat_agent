"""FastAPI dependencies — DB session, Redis cache, task service."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import get_settings
from app.db.session import get_session_factory
from app.services.task_service import TaskService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    settings = get_settings()
    factory = get_session_factory(settings.database_url)
    async with factory() as session:
        yield session


def get_task_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TaskService:
    settings = get_settings()
    cache = request.app.state.redis_cache
    return TaskService(db, cache, settings)
