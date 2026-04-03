"""String enums for health checks and model warmup — single source of valid API values."""

from __future__ import annotations

from enum import StrEnum


class OverallHealthStatus(StrEnum):
    """Aggregated health reported by GET /health."""

    OK = "ok"
    DEGRADED = "degraded"


class ComponentHealthStatus(StrEnum):
    """Per-component status for SQLite, Redis, and the compiled agent graph."""

    OK = "ok"
    ERROR = "error"
    SKIPPED = "skipped"


class ModelWarmupStatus(StrEnum):
    """Model lifecycle phase exposed by GET /health/model and the warmup manager."""

    NOT_STARTED = "not_started"
    DOWNLOADING = "downloading"
    WARMING_UP = "warming_up"
    READY = "ready"
    ERROR = "error"
    SKIPPED = "skipped"
