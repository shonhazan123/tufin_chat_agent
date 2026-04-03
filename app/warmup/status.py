"""Thread-safe model readiness state shared between warmup manager and API."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any


class ModelStatus(str, Enum):
    NOT_STARTED = "not_started"
    DOWNLOADING = "downloading"
    WARMING_UP = "warming_up"
    READY = "ready"
    ERROR = "error"
    SKIPPED = "skipped"


class _ModelState:
    """Singleton holding the current model lifecycle status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = ModelStatus.NOT_STARTED
        self._detail: str = ""

    @property
    def status(self) -> ModelStatus:
        with self._lock:
            return self._status

    @property
    def detail(self) -> str:
        with self._lock:
            return self._detail

    def set(self, status: ModelStatus, detail: str = "") -> None:
        with self._lock:
            self._status = status
            self._detail = detail

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"status": self._status.value, "detail": self._detail}


model_state = _ModelState()
