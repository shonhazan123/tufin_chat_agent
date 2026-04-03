"""Invoke LangGraph — same behavior as legacy root main.py."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from agent.config_loader import load_config
from agent.conversation_memory import conversation_context
from agent.graph import get_graph
from agent.llm_provider_factory import build_llm
from agent.token_usage_tracker import get_usage, reset_usage

logger = logging.getLogger(__name__)
_RECURSION_LIMIT_PER_WAVE = 3


@dataclass
class AgentRunResult:
    final_answer: str
    trace: list[dict]
    failure_flag: bool = False
    latency_ms: int = 0
    total_cached_tokens: int | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    observability: dict[str, Any] = field(default_factory=dict)


def record_assistant_and_schedule_conversation_summary(
    final_answer: str,
    plan: list[dict] | None = None,
) -> None:
    """Append the assistant reply, then refresh the dialogue summary in the background.

    Does not block the HTTP response: summarization runs after the caller returns from
    ``run_agent_task`` (same event loop tick schedules the task; DB work and response follow).
    """
    conversation_context.add_assistant(final_answer)

    if plan:
        tools = list(dict.fromkeys(
            t.get("agent", "") for t in plan if t.get("agent")
        ))
        conversation_context.set_last_tools(tools)
    else:
        conversation_context.set_last_tools([])

    asyncio.create_task(conversation_context.summarize_async(build_llm("responder")))


def _build_observability_json(
    initial_state: dict[str, Any],
    result_state: dict[str, Any],
    usage: Any | None,
) -> dict[str, Any]:
    """Structured record for DB / GET — full graph context for debugging."""
    u = usage
    llm_calls: list[dict[str, Any]] = []
    if u is not None:
        llm_calls = list(u.llm_calls)
    return {
        "version": 1,
        "context_at_start": {
            "task": initial_state.get("task", ""),
            "context_summary": initial_state.get("context_summary", ""),
            "user_key_facts": initial_state.get("user_key_facts", ""),
            "recent_messages_text": initial_state.get("recent_messages_text", ""),
        },
        "plan": result_state.get("plan") or [],
        "results": result_state.get("results") or {},
        "executor_trace": result_state.get("trace") or [],
        "error_context": (result_state.get("error_context") or ""),
        "user_facing_error": (result_state.get("user_facing_error") or ""),
        "failure_flag": bool(result_state.get("failure_flag", False)),
        "response": result_state.get("response", ""),
        "planner_duration_ms": result_state.get("planner_duration_ms"),
        "responder_duration_ms": result_state.get("responder_duration_ms"),
        "llm_calls": llm_calls,
        "totals": {
            "cached_tokens": u.total_cached_tokens if u is not None else None,
            "input_tokens": u.total_input_tokens if u is not None else None,
            "output_tokens": u.total_output_tokens if u is not None else None,
        },
    }


async def run_agent_task(task: str) -> AgentRunResult:
    cfg = load_config()
    graph = get_graph()

    reset_usage()

    conversation_context.add_user(task)

    ctx_summary = conversation_context.summary
    ctx_key_facts = conversation_context.user_key_facts
    ctx_recent = conversation_context.format_recent_messages()

    logger.info(
        "Graph input context — summary: %r, key_facts: %r, recent_len: %d chars",
        ctx_summary[:150] if ctx_summary else "(none)",
        ctx_key_facts[:150] if ctx_key_facts else "(none)",
        len(ctx_recent),
    )

    initial_state: dict[str, Any] = {
        "task": task,
        "context_summary": ctx_summary,
        "user_key_facts": ctx_key_facts,
        "recent_messages_text": ctx_recent,
        "plan": [],
        "results": {},
        "trace": [],
        "response": "",
        "error_context": "",
        "user_facing_error": "",
        "failure_flag": False,
    }

    t0 = time.perf_counter()
    result = await graph.ainvoke(
        initial_state,
        config={"recursion_limit": cfg["executor"]["max_waves"] * _RECURSION_LIMIT_PER_WAVE},
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    answer = result.get("response", "I was unable to generate a response.")
    trace = result.get("trace", [])
    failure_flag = bool(result.get("failure_flag", False))

    usage = get_usage()
    obs = _build_observability_json(initial_state, result, usage)
    cached = usage.total_cached_tokens if usage is not None else None
    inp = usage.total_input_tokens if usage is not None else None
    out = usage.total_output_tokens if usage is not None else None

    record_assistant_and_schedule_conversation_summary(answer, plan=result.get("plan"))

    return AgentRunResult(
        final_answer=answer,
        trace=trace,
        failure_flag=failure_flag,
        latency_ms=latency_ms,
        total_cached_tokens=cached,
        total_input_tokens=inp,
        total_output_tokens=out,
        observability=obs,
    )
