"""Orchestration: SQLite task rows + Redis cache + agent runner."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent.yaml_config import load_config
from app.cache.redis_cache import RedisCache
from app.db.models import Task, TaskStatus
from app.db.task_repository import TaskRepository
from app.settings import Settings
from app.integrations.agent_runner import run_agent_task
from app.schemas.task import TaskResponse

logger = logging.getLogger(__name__)


def _cache_model_hint() -> str:
    try:
        cfg = load_config()
        return str(cfg.get("agents", {}).get("responder", {}).get("model", ""))
    except Exception:
        return ""


class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        cache: RedisCache,
        settings: Settings,
    ) -> None:
        self._session = session
        self._repo = TaskRepository(session)
        self._cache = cache
        self._settings = settings

    async def create_and_run_task(self, task_text: str) -> TaskResponse:
        normalized = task_text.strip()
        task = await self._repo.create_pending(normalized)
        await self._session.commit()

        hint = _cache_model_hint()
        cache_key = self._cache.build_cache_key(normalized, hint)
        cached = await self._cache.get_cached_response(cache_key)
        if cached is not None:
            final_answer = str(cached.get("final_answer", ""))
            trace = list(cached.get("trace", []))
            await self._repo.complete(
                task.id,
                final_answer,
                trace,
                status=TaskStatus.cached,
            )
            await self._session.commit()
            return TaskResponse(
                task_id=task.id,
                final_answer=final_answer,
                trace=trace,
            )

        await self._repo.mark_running(task.id)
        await self._session.commit()

        try:
            result = await run_agent_task(normalized)
        except Exception as exc:
            logger.exception("Agent execution failed")
            await self._session.rollback()
            await self._repo.fail(task.id, str(exc))
            await self._session.commit()
            raise

        await self._repo.complete(
            task.id,
            result.final_answer,
            result.trace,
            status=TaskStatus.completed,
        )
        await self._session.commit()

        await self._cache.set_cached_response(
            cache_key,
            {"final_answer": result.final_answer, "trace": result.trace},
            self._settings.cache_ttl_seconds,
        )

        return TaskResponse(
            task_id=task.id,
            final_answer=result.final_answer,
            trace=result.trace,
        )

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self._repo.get_by_id(task_id)

    def to_response(self, task: Task) -> TaskResponse:
        return TaskResponse(
            task_id=task.id,
            final_answer=task.final_answer or "",
            trace=task.trace_json or [],
        )
