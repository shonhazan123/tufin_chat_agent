"""Base classes and registry for the tool system.

ToolSpec       — declarative tool metadata
BaseToolAgent  — LLM tools: planner params first, then LLM recovery on failure
BaseFunctionTool — base for pure function tools
AgentRegistry  — singleton registry with autodiscovery support
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from agent.llm import build_llm, get_llm_semaphore
from agent.yaml_config import load_config

logger = logging.getLogger(__name__)


class ToolExtractionError(Exception):
    """Raised when a tool LLM fails to produce valid JSON after inner parse retries."""


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return t


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

    Subclasses must:
    - Set ``spec`` (ToolSpec with type="llm")
    - Set ``SYSTEM`` (static system prompt string — module-level constant)
    - Implement ``_tool_executer(params: dict) -> dict``

    Execution model:
    1. If the planner supplied non-empty ``params``, ``_tool_executer`` runs first (no tool LLM).
    2. If that raises, or params were missing/empty, the tool LLM produces JSON args
       (with optional error feedback from the failed call), then ``_tool_executer`` runs again.
    3. Outer attempts are capped by ``executor.max_tool_attempts`` (default 2).
    """

    spec: ToolSpec
    SYSTEM: str

    def __init__(self) -> None:
        self.llm = build_llm(self.spec.name)
        cfg = load_config()
        agent_cfg = cfg["agents"].get(self.spec.name, {})
        self.max_retries: int = agent_cfg.get("max_retries", 3)
        self.timeout: int = cfg["executor"]["tool_timeout_seconds"]
        self.max_tool_attempts: int = cfg["executor"].get("max_tool_attempts", 2)

    async def run(
        self,
        user_msg: str,
        sub_task: str,
        prior_results: dict[str, Any],
        planner_params: dict[str, Any] | None = None,
        context_summary: str = "",
    ) -> dict[str, Any]:
        """Run ``_tool_executer`` using planner args when present; on failure, use tool LLM to recover."""
        params: dict[str, Any] | None = (
            dict(planner_params) if planner_params else None
        )
        last_exc: BaseException | None = None

        for attempt in range(self.max_tool_attempts):
            try:
                need_llm = (not params) or (last_exc is not None)
                if need_llm:
                    params = await self._llm_extract_params(
                        user_msg=user_msg,
                        sub_task=sub_task,
                        prior_results=prior_results,
                        context_summary=context_summary,
                        cause=last_exc,
                        previous_params=params,
                    )
                assert params is not None
                return await self._tool_executer(params)
            except Exception as e:
                last_exc = e
                logger.warning(
                    "%s: attempt %d/%d failed: %s",
                    self.spec.name,
                    attempt + 1,
                    self.max_tool_attempts,
                    e,
                )
                if attempt + 1 >= self.max_tool_attempts:
                    raise

        raise RuntimeError(f"{self.spec.name}: exhausted attempts (unreachable)")

    async def _llm_extract_params(
        self,
        user_msg: str,
        sub_task: str,
        prior_results: dict[str, Any],
        context_summary: str,
        cause: BaseException | None,
        previous_params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Invoke the tool LLM; retry on JSON parse errors only (up to ``max_retries``)."""
        parse_feedback = ""
        for parse_attempt in range(self.max_retries):
            parts = [
                f"User request: {user_msg}",
                f"Conversation context (summary): {context_summary or '(none)'}",
                f"Sub-task from plan: {sub_task}",
                f"Prior tool results: {json.dumps(prior_results, default=str)}",
            ]
            if cause is not None:
                parts.append(f"Previous execution failed with: {cause!s}")
            if previous_params is not None:
                parts.append(
                    "Previous parameters attempted: "
                    f"{json.dumps(previous_params, default=str)}"
                )
            if parse_feedback:
                parts.append(
                    f"Your previous reply was not valid JSON: {parse_feedback}. "
                    "Reply with a single JSON object only — no markdown fences."
                )
            else:
                parts.append(
                    "Reply with a single JSON object only — no markdown, no fences, "
                    "no explanation outside the JSON."
                )
            human_content = "\n".join(parts)

            async with get_llm_semaphore():
                params_msg = await asyncio.wait_for(
                    self.llm.ainvoke([
                        SystemMessage(content=self.SYSTEM),
                        HumanMessage(content=human_content),
                    ]),
                    timeout=self.timeout,
                )

            raw = _strip_json_fence(params_msg.content)
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("JSON root must be an object")
                return parsed
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                parse_feedback = str(exc)
                logger.warning(
                    "%s: JSON parse failed (inner %d/%d): %s",
                    self.spec.name,
                    parse_attempt + 1,
                    self.max_retries,
                    parse_feedback,
                )

        raise ToolExtractionError(
            f"{self.spec.name}: tool LLM did not return valid JSON after "
            f"{self.max_retries} parse attempts"
        )

    @abstractmethod
    async def _tool_executer(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute the backend (API call, eval, conversion, etc.) with structured params."""
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
