"""Base classes and registry for the tool system.

ToolSpec          — declarative tool metadata
ToolInvocation    — graph ``state`` + plan task row; tools read fields via properties
BaseToolAgent     — ``run(state, plan_task)`` builds ``ToolInvocation``; shared parameter-specialist LLM helper
BaseFunctionTool  — base for pure function tools
AgentRegistry     — singleton registry with autodiscovery support
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import abstractmethod
from typing import Any, Mapping

from langchain_core.messages import HumanMessage, SystemMessage

from agent.config_loader import load_config
from agent.llm_provider_factory import build_llm, get_llm_semaphore
from agent.token_usage_tracker import record_llm_call
from agent.types.tool_types import (
    ToolInvocation,
    ToolParamValidationError,
    ToolSpec,
    UserFacingToolError,
)

logger = logging.getLogger(__name__)


def strip_json_fence(text: str) -> str:
    """Strip optional markdown fences from model output (tools use when parsing JSON)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    elif stripped.endswith("```"):
        stripped = stripped[: stripped.rfind("```")].strip()
    return stripped


class BaseToolAgent:
    """Base class for LLM-backed tools.

    Subclasses implement ``_tool_executor``. Parameter extraction uses
    ``_invoke_parameter_specialist_llm`` when planner params are insufficient.
    """

    spec: ToolSpec

    def __init__(self) -> None:
        self.llm = build_llm(self.spec.name)
        config = load_config()
        self.timeout: int = config["executor"]["tool_timeout_seconds"]

    async def run(
        self,
        state: Mapping[str, Any],
        plan_task: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build ``ToolInvocation`` from graph state + plan row; delegate to ``_tool_executor``."""
        tool_invocation = ToolInvocation.from_graph(state, plan_task)
        return await self._tool_executor(tool_invocation)

    async def _invoke_parameter_specialist_llm(
        self, tool_invocation: ToolInvocation
    ) -> dict[str, Any]:
        """One-shot LLM call to extract structured params (identical human-message contract for all tools).

        Prior results are exactly ``tool_invocation.prior_results`` (``depends_on``-scoped only).
        """
        parts = [
            f"User request: {tool_invocation.user_msg}",
            f"Conversation context (summary): {tool_invocation.context_summary or '(none)'}",
            f"Sub-task from plan: {tool_invocation.sub_task}",
            f"Prior tool results: {json.dumps(tool_invocation.prior_results, default=str)}",
            "Reply with a single JSON object only — no markdown, no fences, "
            "no explanation outside the JSON.",
        ]
        human_content = "\n".join(parts)
        specialist_prompt = self.spec.system_prompt or ""
        messages = [
            SystemMessage(content=specialist_prompt),
            HumanMessage(content=human_content),
        ]
        async with get_llm_semaphore():
            params_msg = await asyncio.wait_for(
                self.llm.ainvoke(messages),
                timeout=self.timeout,
            )
        record_llm_call(
            f"tool:{self.spec.name}",
            params_msg,
            messages=messages,
            model=self.llm.model_name,
        )
        raw = strip_json_fence(params_msg.content)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("JSON root must be an object")
        return parsed

    @abstractmethod
    async def _tool_executor(self, tool_invocation: ToolInvocation) -> dict[str, Any]:
        """Tool-specific: backend; call ``_invoke_parameter_specialist_llm`` when planner params are missing."""
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
        config = load_config()
        tool_config = config.get("tools", {}).get(spec.name, {})

        def decorator(cls: type) -> type:
            if not tool_config.get("enabled", True):
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


__all__ = (
    "AgentRegistry",
    "BaseFunctionTool",
    "BaseToolAgent",
    "ToolInvocation",
    "ToolParamValidationError",
    "ToolSpec",
    "UserFacingToolError",
    "registry",
    "strip_json_fence",
)
