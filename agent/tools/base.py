"""Base classes and registry for the tool system.

ToolSpec       — declarative tool metadata
BaseToolAgent  — base for LLM tools (semaphore + retry loop)
BaseFunctionTool — base for pure function tools
AgentRegistry  — singleton registry with autodiscovery support
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from agent.yaml_config import load_config
from agent.llm import build_llm, get_llm_semaphore

logger = logging.getLogger(__name__)


class ToolExtractionError(Exception):
    """Raised when an LLM tool fails to extract valid params after all retries."""


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
    """Base class for LLM-powered tools.

    Subclasses must:
    - Set ``spec`` (ToolSpec with type="llm")
    - Set ``SYSTEM`` (static system prompt string — module-level constant)
    - Implement ``_call_api(params: dict) -> dict``
    """

    spec: ToolSpec
    SYSTEM: str

    def __init__(self) -> None:
        self.llm = build_llm(self.spec.name)
        cfg = load_config()
        agent_cfg = cfg["agents"].get(self.spec.name, {})
        self.max_retries: int = agent_cfg.get("max_retries", 3)
        self.timeout: int = cfg["executor"]["tool_timeout_seconds"]

    async def run(
        self,
        user_msg: str,
        sub_task: str,
        prior_results: dict[str, Any],
    ) -> dict[str, Any]:
        """LLM extraction → API call, with retry loop.

        Semaphore is held ONLY during the LLM call, released before API call.
        """
        feedback = ""
        for attempt in range(self.max_retries):
            async with get_llm_semaphore():
                human_content = (
                    f"User: {user_msg}\nTask: {sub_task}\nContext: {prior_results}"
                )
                if feedback:
                    human_content += (
                        f"\n\nPrevious output was invalid: {feedback}. Try again."
                    )
                params_msg = await asyncio.wait_for(
                    self.llm.ainvoke([
                        SystemMessage(content=self.SYSTEM),
                        HumanMessage(content=human_content),
                    ]),
                    timeout=self.timeout,
                )
            try:
                params = json.loads(params_msg.content)
                return await self._call_api(params)
            except json.JSONDecodeError as exc:
                feedback = str(exc)
                logger.warning(
                    "%s: JSON parse failed (attempt %d/%d): %s",
                    self.spec.name, attempt + 1, self.max_retries, feedback,
                )

        raise ToolExtractionError(
            f"{self.spec.name}: LLM extraction failed after {self.max_retries} retries"
        )

    @abstractmethod
    async def _call_api(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute the external API call with extracted params."""
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
            if spec.type == "function" and spec.input_schema:
                input_fields = ", ".join(
                    f"{k}: {v}" for k, v in spec.input_schema.items()
                )
                line += f"\n  Input params: {input_fields}"
            lines.append(line)
        return "\n".join(lines)


registry = AgentRegistry()
