"""Base classes and registry for the tool system.

ToolSpec          — declarative tool metadata
ToolInvocation    — graph ``state`` + plan task row; tools read fields via properties
BaseToolAgent     — ``run(state, plan_task)`` builds ``ToolInvocation``; each tool calls ``self.llm`` when params are missing
BaseFunctionTool  — base for pure function tools
AgentRegistry     — singleton registry with autodiscovery support
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from agent.llm import build_llm
from agent.yaml_config import load_config

logger = logging.getLogger(__name__)


def strip_json_fence(text: str) -> str:
    """Strip optional markdown fences from model output (tools use when parsing JSON)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    elif t.endswith("```"):
        t = t[: t.rfind("```")].strip()
    return t


class ToolParamValidationError(Exception):
    """Raised when a tool cannot obtain valid structured params (tool-specific)."""


class UserFacingToolError(Exception):
    """Tool failure with a short, user-safe message (no stack traces, no internal IDs)."""


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
        p = self.plan_task.get("params")
        if p is None:
            return {}
        return dict(p) if isinstance(p, dict) else {}

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
        st: dict[str, Any] = {
            "task": task,
            "results": dict(prior_results or {}),
            "context_summary": context_summary,
        }
        pt: dict[str, Any] = {
            "sub_task": sub_task,
            "params": dict(planner_params) if planner_params is not None else {},
            "depends_on": list(depends_on) if depends_on else [],
        }
        return cls(state=st, plan_task=pt)


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


class BaseToolAgent:
    """Base class for LLM-backed tools.

    Subclasses implement ``_tool_executor``. Call ``self.llm.ainvoke`` **only** when planner
    params are missing what the tool needs — one call, no retry loops (implement in the tool file).
    """

    spec: ToolSpec
    SYSTEM: str

    def __init__(self) -> None:
        self.llm = build_llm(self.spec.name)
        cfg = load_config()
        self.timeout: int = cfg["executor"]["tool_timeout_seconds"]

    async def run(
        self,
        state: Mapping[str, Any],
        plan_task: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build ``ToolInvocation`` from graph state + plan row; delegate to ``_tool_executor``."""
        inv = ToolInvocation.from_graph(state, plan_task)
        return await self._tool_executor(inv)

    @abstractmethod
    async def _tool_executor(self, inv: ToolInvocation) -> dict[str, Any]:
        """Tool-specific: backend; call ``self.llm`` once only if params from the planner are missing."""
        ...


class BaseFunctionTool:
    """Base class for pure-function tools (no LLM, no semaphore).

    Subclasses must:
    - Set ``spec`` (ToolSpec with type="function")
    - Implement ``call(params: dict) -> dict``
    """

    spec: ToolSpec

    @abstractmethod
    async def call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool with structured params from the planner."""
        ...


class AgentRegistry:
    """Singleton registry for all tools. Populated by @register decorators."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseToolAgent | BaseFunctionTool] = {}
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec):
        """Class decorator that registers a tool agent with its spec."""
        cfg = load_config()
        tool_cfg = cfg.get("tools", {}).get(spec.name, {})

        def decorator(cls: type) -> type:
            if not tool_cfg.get("enabled", True):
                logger.info("Tool %s is disabled in config — skipping", spec.name)
                return cls

            cls.spec = spec
            instance = cls()
            self._agents[spec.name] = instance
            self._specs[spec.name] = spec
            logger.info("Registered tool: %s (type=%s)", spec.name, spec.type)
            return cls

        return decorator

    def get(self, name: str) -> BaseToolAgent | BaseFunctionTool:
        """Look up a registered tool by name."""
        if name not in self._agents:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(self._agents)}")
        return self._agents[name]

    def all_specs(self) -> list[ToolSpec]:
        """Return all registered ToolSpecs."""
        return list(self._specs.values())

    def planner_agent_block(self) -> str:
        """Build the tool description block for the planner system prompt."""
        lines: list[str] = []
        for spec in self._specs.values():
            output_fields = ", ".join(
                f"{k}: {v.__name__}" for k, v in spec.output_schema.items()
            )
            line = f"- {spec.name} (type: {spec.type}) — {spec.purpose}"
            line += f"\n  Output fields: {output_fields}"
            if spec.input_schema:
                input_fields = ", ".join(
                    f"{k}: {v}" for k, v in spec.input_schema.items()
                )
                if spec.type == "function":
                    line += f"\n  Input params: {input_fields}"
                else:
                    line += (
                        f"\n  Planner MUST include params with: {input_fields}; "
                        f"also set sub_task as a short human description."
                    )
            lines.append(line)
        return "\n".join(lines)


registry = AgentRegistry()
