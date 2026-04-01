"""Task API DTOs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class TaskRequest(BaseModel):
    task: str = Field(min_length=1, description="User task text")


class TaskResponse(BaseModel):
    task_id: UUID
    final_answer: str
    trace: list[dict] = Field(default_factory=list)
