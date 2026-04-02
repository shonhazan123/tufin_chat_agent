"""Task persistence — repository pattern."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, TaskStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(self, task_text: str) -> Task:
        task = Task(task_text=task_text, status=TaskStatus.pending)
        self._session.add(task)
        await self._session.flush()
        await self._session.refresh(task)
        return task

    async def mark_running(self, task_id: uuid.UUID) -> None:
        task = await self.get_by_id(task_id)
        if task:
            task.status = TaskStatus.running
            await self._session.flush()

    async def complete(
        self,
        task_id: uuid.UUID,
        final_answer: str,
        trace: list[dict],
        *,
        latency_ms: int | None = None,
        total_input_tokens: int | None = None,
        total_output_tokens: int | None = None,
        observability_json: dict[str, Any] | None = None,
        status: TaskStatus = TaskStatus.completed,
    ) -> None:
        task = await self.get_by_id(task_id)
        if not task:
            return
        task.status = status
        task.final_answer = final_answer
        task.trace_json = trace
        task.latency_ms = latency_ms
        task.total_input_tokens = total_input_tokens
        task.total_output_tokens = total_output_tokens
        task.observability_json = observability_json
        task.completed_at = _utcnow()
        task.error_message = None
        await self._session.flush()

    async def fail(self, task_id: uuid.UUID, error_message: str) -> None:
        task = await self.get_by_id(task_id)
        if not task:
            return
        task.status = TaskStatus.failed
        task.error_message = error_message
        task.completed_at = _utcnow()
        await self._session.flush()

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        result = await self._session.execute(select(Task).where(Task.id == task_id))
        return result.scalar_one_or_none()
