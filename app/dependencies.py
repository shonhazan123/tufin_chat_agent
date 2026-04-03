"""FastAPI dependencies — database session factory and task orchestration service."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.services.task_orchestration_service import TaskOrchestrationService
from app.settings import get_settings


async def get_database_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield one async SQLAlchemy session per request (closes after response)."""
    application_settings = get_settings()
    database_session_factory = get_session_factory(application_settings.database_url)
    async with database_session_factory() as database_session:
        yield database_session


def get_task_orchestration_service(
    http_request: Request,
    database_session: AsyncSession = Depends(get_database_session),
) -> TaskOrchestrationService:
    """Construct the task orchestrator with the request-scoped DB session and Redis cache."""
    application_settings = get_settings()
    redis_response_cache = http_request.app.state.redis_cache
    return TaskOrchestrationService(
        database_session,
        redis_response_cache,
        application_settings,
    )


# Backward-compatible name for docs and external references.
get_task_service = get_task_orchestration_service
