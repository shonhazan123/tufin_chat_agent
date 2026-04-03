"""Orchestration: SQLite task rows, Redis answer cache, and LangGraph agent runs."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent.config_loader import load_config
from agent.conversation_memory import conversation_context
from app.cache.redis_cache import RedisCache
from app.db.models import Task, TaskStatus
from app.db.task_repository import TaskRepository
from app.integrations.agent_runner import (
    record_assistant_and_schedule_conversation_summary,
    run_agent_task,
)
from app.schemas.task_schemas import TaskDebugResponse, TaskDetailResponse, TaskSubmitResponse
from app.services.reasoning_tree_builder import build_reasoning_tree
from app.settings import Settings

logger = logging.getLogger(__name__)


def _parse_optional_integer(raw_value: Any) -> int | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, int):
        return raw_value
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _get_responder_model_name_for_cache_key() -> str:
    try:
        agent_configuration = load_config()
        return str(
            agent_configuration.get("agents", {})
            .get("responder", {})
            .get("model", ""),
        )
    except Exception:
        return ""


def _extract_observability_from_cached_response(
    cached_response_payload: dict[str, Any],
    executor_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    observability_from_cache = cached_response_payload.get("observability_json")
    if isinstance(observability_from_cache, dict) and observability_from_cache:
        return observability_from_cache
    return {
        "version": 1,
        "executor_trace": executor_trace,
        "note": "legacy_cache_payload",
    }


class TaskOrchestrationService:
    """Create tasks, serve cache hits, invoke the agent, persist traces and metrics."""

    def __init__(
        self,
        database_session: AsyncSession,
        redis_response_cache: RedisCache,
        application_settings: Settings,
    ) -> None:
        self._database_session = database_session
        self._task_repository = TaskRepository(database_session)
        self._redis_response_cache = redis_response_cache
        self._application_settings = application_settings

    async def create_and_run_task(self, task_text: str) -> TaskSubmitResponse:
        normalized_task_text = task_text.strip()
        task_row = await self._task_repository.create_pending(normalized_task_text)
        await self._database_session.commit()

        responder_model_name_hint = _get_responder_model_name_for_cache_key()
        cache_lookup_key = self._redis_response_cache.build_cache_key(
            normalized_task_text,
            responder_model_name_hint,
        )
        cached_response_payload = await self._redis_response_cache.get_cached_response(
            cache_lookup_key,
        )
        if cached_response_payload is not None:
            final_answer_text = str(cached_response_payload.get("final_answer", ""))
            executor_trace = list(cached_response_payload.get("trace", []))
            observability_data = _extract_observability_from_cached_response(
                cached_response_payload,
                executor_trace,
            )
            latency_milliseconds = _parse_optional_integer(
                cached_response_payload.get("latency_ms"),
            )
            total_cached_tokens = _parse_optional_integer(
                cached_response_payload.get("total_cached_tokens"),
            )
            total_input_tokens = _parse_optional_integer(
                cached_response_payload.get("total_input_tokens"),
            )
            total_output_tokens = _parse_optional_integer(
                cached_response_payload.get("total_output_tokens"),
            )
            conversation_context.add_user(normalized_task_text)
            record_assistant_and_schedule_conversation_summary(final_answer_text)
            await self._task_repository.complete(
                task_row.id,
                final_answer_text,
                executor_trace,
                latency_ms=latency_milliseconds,
                total_cached_tokens=total_cached_tokens,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                observability_json=observability_data,
                status=TaskStatus.cached,
            )
            await self._database_session.commit()
            return TaskSubmitResponse(
                task_id=task_row.id,
                final_answer=final_answer_text,
                latency_ms=latency_milliseconds,
                total_cached_tokens=total_cached_tokens,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
            )

        await self._task_repository.mark_running(task_row.id)
        await self._database_session.commit()

        try:
            agent_run_result = await run_agent_task(normalized_task_text)
        except Exception as exc:
            logger.exception("Agent execution failed")
            await self._database_session.rollback()
            await self._task_repository.fail(task_row.id, str(exc))
            await self._database_session.commit()
            raise

        await self._task_repository.complete(
            task_row.id,
            agent_run_result.final_answer,
            agent_run_result.trace,
            latency_ms=agent_run_result.latency_ms,
            total_cached_tokens=agent_run_result.total_cached_tokens,
            total_input_tokens=agent_run_result.total_input_tokens,
            total_output_tokens=agent_run_result.total_output_tokens,
            observability_json=agent_run_result.observability,
            status=TaskStatus.completed,
        )
        await self._database_session.commit()

        await self._redis_response_cache.set_cached_response(
            cache_lookup_key,
            {
                "final_answer": agent_run_result.final_answer,
                "trace": agent_run_result.trace,
                "latency_ms": agent_run_result.latency_ms,
                "total_cached_tokens": agent_run_result.total_cached_tokens,
                "total_input_tokens": agent_run_result.total_input_tokens,
                "total_output_tokens": agent_run_result.total_output_tokens,
                "observability_json": agent_run_result.observability,
            },
            self._application_settings.cache_ttl_seconds,
        )

        return TaskSubmitResponse(
            task_id=task_row.id,
            final_answer=agent_run_result.final_answer,
            latency_ms=agent_run_result.latency_ms,
            total_cached_tokens=agent_run_result.total_cached_tokens,
            total_input_tokens=agent_run_result.total_input_tokens,
            total_output_tokens=agent_run_result.total_output_tokens,
        )

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self._task_repository.get_by_id(task_id)

    def to_detail_response(self, task_row: Task) -> TaskDetailResponse:
        return TaskDetailResponse(
            task_id=task_row.id,
            final_answer=task_row.final_answer or "",
            latency_ms=task_row.latency_ms,
            total_cached_tokens=task_row.total_cached_tokens,
            total_input_tokens=task_row.total_input_tokens,
            total_output_tokens=task_row.total_output_tokens,
            observability=task_row.observability_json or {},
        )

    def to_debug_response(self, task_row: Task) -> TaskDebugResponse:
        reasoning_tree = build_reasoning_tree(
            task_row.observability_json or {},
            task_row.task_text or "",
        )
        return TaskDebugResponse(
            task_id=task_row.id,
            task_text=task_row.task_text or "",
            status=task_row.status.value if task_row.status else "unknown",
            final_answer=task_row.final_answer or "",
            error_message=task_row.error_message,
            created_at=task_row.created_at,
            completed_at=task_row.completed_at,
            latency_ms=task_row.latency_ms,
            total_cached_tokens=task_row.total_cached_tokens,
            total_input_tokens=task_row.total_input_tokens,
            total_output_tokens=task_row.total_output_tokens,
            reasoning_tree=reasoning_tree,
        )
