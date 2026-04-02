"""Orchestration: SQLite task rows + Redis cache + agent runner."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent.context import conversation_context
from agent.yaml_config import load_config
from app.cache.redis_cache import RedisCache
from app.db.models import Task, TaskStatus
from app.db.task_repository import TaskRepository
from app.integrations.agent_runner import record_assistant_and_schedule_conversation_summary, run_agent_task
from app.settings import Settings
from app.schemas.task import TaskDetailResponse, TaskSubmitResponse

logger = logging.getLogger(__name__)


def _cache_model_hint() -> str:
    try:
        cfg = load_config()
        return str(cfg.get("agents", {}).get("responder", {}).get("model", ""))
    except Exception:
        return ""


def _observability_from_cache(cached: dict, trace: list[dict]) -> dict:
    obs = cached.get("observability_json")
    if isinstance(obs, dict) and obs:
        return obs
    return {
        "version": 1,
        "executor_trace": trace,
        "note": "legacy_cache_payload",
    }


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

    async def create_and_run_task(self, task_text: str) -> TaskSubmitResponse:
        normalized = task_text.strip()
        task = await self._repo.create_pending(normalized)
        await self._session.commit()

        hint = _cache_model_hint()
        cache_key = self._cache.build_cache_key(normalized, hint)
        cached = await self._cache.get_cached_response(cache_key)
        if cached is not None:
            final_answer = str(cached.get("final_answer", ""))
            trace = list(cached.get("trace", []))
            obs = _observability_from_cache(cached, trace)
            latency_ms = cached.get("latency_ms")
            if latency_ms is not None and not isinstance(latency_ms, int):
                try:
                    latency_ms = int(latency_ms)
                except (TypeError, ValueError):
                    latency_ms = None
            tin = cached.get("total_input_tokens")
            tout = cached.get("total_output_tokens")
            if tin is not None and not isinstance(tin, int):
                try:
                    tin = int(tin)
                except (TypeError, ValueError):
                    tin = None
            if tout is not None and not isinstance(tout, int):
                try:
                    tout = int(tout)
                except (TypeError, ValueError):
                    tout = None
            conversation_context.add_user(normalized)
            record_assistant_and_schedule_conversation_summary(final_answer)
            await self._repo.complete(
                task.id,
                final_answer,
                trace,
                latency_ms=latency_ms,
                total_input_tokens=tin,
                total_output_tokens=tout,
                observability_json=obs,
                status=TaskStatus.cached,
            )
            await self._session.commit()
            return TaskSubmitResponse(
                task_id=task.id,
                final_answer=final_answer,
                latency_ms=latency_ms,
                total_input_tokens=tin,
                total_output_tokens=tout,
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
            latency_ms=result.latency_ms,
            total_input_tokens=result.total_input_tokens,
            total_output_tokens=result.total_output_tokens,
            observability_json=result.observability,
            status=TaskStatus.completed,
        )
        await self._session.commit()

        await self._cache.set_cached_response(
            cache_key,
            {
                "final_answer": result.final_answer,
                "trace": result.trace,
                "latency_ms": result.latency_ms,
                "total_input_tokens": result.total_input_tokens,
                "total_output_tokens": result.total_output_tokens,
                "observability_json": result.observability,
            },
            self._settings.cache_ttl_seconds,
        )

        return TaskSubmitResponse(
            task_id=task.id,
            final_answer=result.final_answer,
            latency_ms=result.latency_ms,
            total_input_tokens=result.total_input_tokens,
            total_output_tokens=result.total_output_tokens,
        )

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self._repo.get_by_id(task_id)

    def to_detail_response(self, task: Task) -> TaskDetailResponse:
        return TaskDetailResponse(
            task_id=task.id,
            final_answer=task.final_answer or "",
            latency_ms=task.latency_ms,
            total_input_tokens=task.total_input_tokens,
            total_output_tokens=task.total_output_tokens,
            observability=task.observability_json or {},
        )
