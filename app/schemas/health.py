"""Health check response."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="ok or degraded")
    sqlite: str = Field(description="ok or error")
    redis: str = Field(description="ok, error, or skipped")
