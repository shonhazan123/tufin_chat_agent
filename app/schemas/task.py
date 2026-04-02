"""Task API DTOs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TaskRequest(BaseModel):
    task: str = Field(min_length=1, description="User task text")


class TaskSubmitResponse(BaseModel):
    """POST /task — slim body (no full observability blob)."""

    task_id: UUID
    final_answer: str
    latency_ms: int | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None


class TaskDetailResponse(TaskSubmitResponse):
    """GET /tasks/{id} — includes persisted observability for debugging."""

    observability: dict[str, Any] = Field(default_factory=dict)
