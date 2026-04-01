"""Placeholder for future OpenTelemetry hooks (no collector required)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def span(_name: str) -> Iterator[None]:
    yield
