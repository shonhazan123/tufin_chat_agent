"""Thread-safe model readiness state shared between warmup manager and API."""

from __future__ import annotations

import threading
from typing import Any

from app.types.health_status_types import ModelWarmupStatus


# Backward-compatible name for callers that import ModelStatus from app.warmup.
ModelStatus = ModelWarmupStatus


class _ModelState:
    """Singleton holding the current model lifecycle status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = ModelWarmupStatus.NOT_STARTED
        self._detail: str = ""

    @property
    def status(self) -> ModelWarmupStatus:
        with self._lock:
            return self._status

    @property
    def detail(self) -> str:
        with self._lock:
            return self._detail

    def set(self, status: ModelWarmupStatus, detail: str = "") -> None:
        with self._lock:
            self._status = status
            self._detail = detail

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"status": self._status.value, "detail": self._detail}


model_state = _ModelState()
