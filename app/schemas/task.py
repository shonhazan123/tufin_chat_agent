"""Task API DTOs."""

from __future__ import annotations

from datetime import datetime
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


# ---------------------------------------------------------------------------
# Debug / reasoning tree schemas
# ---------------------------------------------------------------------------


class ReasoningStep(BaseModel):
    """One node in the reasoning tree (planner, tool, or responder)."""

    id: str
    label: str
    node_type: str
    status: str
    model: str | None = None
    duration_ms: int | None = None
    tokens: dict[str, int | None] | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    wave: int | None = None
    children: list[ReasoningStep] = Field(default_factory=list)


class TaskDebugResponse(BaseModel):
    """GET /tasks/{id}/debug — full reasoning tree for the debug sidebar."""

    task_id: UUID
    task_text: str
    status: str
    final_answer: str
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    latency_ms: int | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    reasoning_tree: list[ReasoningStep]
