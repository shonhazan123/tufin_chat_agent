"""Pydantic response bodies for health and model-readiness endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.types.health_status_types import (
    ComponentHealthStatus,
    ModelWarmupStatus,
    OverallHealthStatus,
)


class HealthResponse(BaseModel):
    """Body of GET /health — dependency and agent readiness."""

    status: OverallHealthStatus = Field(description="Aggregated status: ok or degraded")
    sqlite: ComponentHealthStatus = Field(description="Database probe: ok or error")
    redis: ComponentHealthStatus = Field(description="Cache probe: ok, error, or skipped")
    agent: ComponentHealthStatus = Field(
        description="LangGraph compile/load probe: ok or error",
    )
    provider: str | None = Field(
        default=None,
        description="Active LLM provider: openai or ollama",
    )
    models: dict[str, Any] | None = Field(
        default=None,
        description="Resolved model id per agent role name",
    )


class ModelStatusResponse(BaseModel):
    """Body of GET /health/model — model download/warmup lifecycle for the chat UI."""

    status: ModelWarmupStatus = Field(
        description="not_started, downloading, warming_up, ready, error, or skipped",
    )
    detail: str = Field(default="", description="Human-readable detail about current phase")
