"""Tool metadata, invocation context, and tool-specific exception types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


@dataclass(frozen=True)
class ToolInvocation:
    """One tool run: graph ``state`` plus the current plan task row.

    The executor passes the live state and the task dict; tools use properties instead of
    unpacking ``user_msg``, ``sub_task``, ``prior_results``, ``planner_params``, ``context_summary``.
    """

    state: Mapping[str, Any]
    plan_task: Mapping[str, Any]

    @property
    def user_msg(self) -> str:
        return str(self.state.get("task", ""))

    @property
    def sub_task(self) -> str:
        return str(self.plan_task.get("sub_task") or "")

    @property
    def prior_results(self) -> dict[str, Any]:
        """Results scoped to ``depends_on`` task ids only (tight context for tool LLM)."""
        all_results = self.state.get("results")
        if not isinstance(all_results, dict):
            return {}
        deps = self.plan_task.get("depends_on") or []
        if not deps:
            return {}
        return {k: v for k, v in all_results.items() if k in deps}

    @property
    def has_dependencies(self) -> bool:
        """True when this task depends on prior tool outputs (always needs LLM extraction)."""
        deps = self.plan_task.get("depends_on") or []
        return bool(deps)

    @property
    def context_summary(self) -> str:
        return str(self.state.get("context_summary") or "")

    @property
    def planner_params(self) -> dict[str, Any]:
        plan_params = self.plan_task.get("params")
        if plan_params is None:
            return {}
        return dict(plan_params) if isinstance(plan_params, dict) else {}

    @classmethod
    def from_graph(
        cls, state: Mapping[str, Any], plan_task: Mapping[str, Any]
    ) -> ToolInvocation:
        return cls(state=state, plan_task=plan_task)

    @classmethod
    def from_parts(
        cls,
        *,
        task: str = "",
        sub_task: str = "",
        prior_results: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        planner_params: dict[str, Any] | None = None,
        context_summary: str = "",
    ) -> ToolInvocation:
        """Minimal state + task row (tests and callers without a full graph)."""
        state_dict: dict[str, Any] = {
            "task": task,
            "results": dict(prior_results or {}),
            "context_summary": context_summary,
        }
        plan_task_dict: dict[str, Any] = {
            "sub_task": sub_task,
            "params": dict(planner_params) if planner_params is not None else {},
            "depends_on": list(depends_on) if depends_on else [],
        }
        return cls(state=state_dict, plan_task=plan_task_dict)


@dataclass
class ToolSpec:
    """Declarative metadata for a tool — the planner reads this to decide routing."""

    name: str
    type: Literal["llm", "function"]
    purpose: str
    output_schema: dict[str, type]
    input_schema: dict[str, str] | None = None
    system_prompt: str | None = None
    default_ttl_seconds: int = 0


class ToolParamValidationError(Exception):
    """Raised when a tool cannot obtain valid structured params (tool-specific)."""


class UserFacingToolError(Exception):
    """Tool failure with a short, user-safe message (no stack traces, no internal IDs)."""
