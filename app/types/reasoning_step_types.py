"""Types for the debug reasoning-tree nodes returned by GET /tasks/{id}/debug."""

from __future__ import annotations

from enum import StrEnum


class ReasoningNodeType(StrEnum):
    """Which graph phase produced this step."""

    PLANNER = "planner"
    TOOL = "tool"
    RESPONDER = "responder"


class ReasoningStepStatus(StrEnum):
    """Whether the step completed successfully."""

    OK = "ok"
    ERROR = "error"
