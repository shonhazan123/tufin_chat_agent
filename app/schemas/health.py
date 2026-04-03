"""Health check response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="ok or degraded")
    sqlite: str = Field(description="ok or error")
    redis: str = Field(description="ok, error, or skipped")
    agent: str = Field(description="ok or error — whether the LangGraph agent is compiled and ready")
    provider: str | None = Field(default=None, description="Active LLM provider: openai or ollama")
    models: dict[str, Any] | None = Field(default=None, description="Model name per agent role")


class ModelStatusResponse(BaseModel):
    status: str = Field(description="not_started, downloading, warming_up, ready, error, or skipped")
    detail: str = Field(default="", description="Human-readable detail about current phase")
