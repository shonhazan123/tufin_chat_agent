"""Graph nodes — planner, executor, failure marker, response, and routing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.context import conversation_context
from agent.llm import build_llm
from agent.tokens import record_llm_call
from agent.memory_format import (
    PLANNER_MEMORY_MAX_TOKENS,
    build_planner_context_block,
    build_responder_memory_block,
)
from agent.prompts import RESPONDER_SYSTEM, build_planner_prompt
from agent.tools.base import UserFacingToolError, registry
from agent.yaml_config import load_config

logger = logging.getLogger(__name__)


async def prepare_responder_context_node(state: dict[str, Any]) -> dict[str, Any]:
    """Graph node: label each tool result as FINAL ANSWER or INTERMEDIATE before the responder.

    A task is "final" when no other task in the plan depends on it — its output
    is the end product the user cares about. Intermediate tasks fed data into
    downstream tools; their results provide background context only.
    """
    plan = state.get("plan") or []
    results = state.get("results") or {}
    if not results:
        return {"responder_tool_context": "Tool results: (none — no tools were executed)"}

    depended_on: set[str] = set()
    for t in plan:
        for dep in t.get("depends_on", []):
            depended_on.add(dep)

    task_meta = {t["id"]: t for t in plan}

    sections: list[str] = []
    for tid, res in results.items():
        meta = task_meta.get(tid, {})
        agent_name = meta.get("agent", "unknown")
        sub_task = meta.get("sub_task", "")
        role = "INTERMEDIATE (context only)" if tid in depended_on else "FINAL ANSWER"
        header = f"[{tid}] {agent_name} — {role}"
        if sub_task:
            header += f"\n  Sub-task: {sub_task}"
        body = json.dumps(res, indent=2, default=str)
        sections.append(f"{header}\n{body}")

    return {"responder_tool_context": "Tool results:\n\n" + "\n\n".join(sections)}


async def planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """Invoke planner LLM to produce a JSON execution plan."""
    llm = build_llm("planner")
    system_prompt = build_planner_prompt()
    cfg = load_config()

    parts = [f"Task: {state['task']}"]

    last_tools = conversation_context.last_tools_used
    if last_tools:
        parts.append(f"[Tools used in previous turn]: {', '.join(last_tools)}")

    planner_mem = build_planner_context_block(
        recent_messages=(state.get("recent_messages_text") or "").strip(),
        context_summary=(state.get("context_summary") or "").strip(),
        max_tokens=PLANNER_MEMORY_MAX_TOKENS,
    ).strip()
    if planner_mem:
        parts.append(f"[Planner memory — last messages + summary; ~{PLANNER_MEMORY_MAX_TOKENS} token budget]\n{planner_mem}")

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(parts)),
    ]

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        llm.ainvoke(messages),
        timeout=cfg["executor"]["tool_timeout_seconds"],
    )
    planner_ms = int((time.perf_counter() - t0) * 1000)
    record_llm_call("planner", result, messages=messages, model=llm.model_name)

    text = result.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        err = f"Planner JSON parse error: {exc}"
        logger.error("Planner returned invalid JSON: %s", exc)
        return {"error_context": err, "planner_duration_ms": planner_ms}

    tasks = raw.get("tasks", raw) if isinstance(raw, dict) else raw
    logger.info("Planner produced %d task(s)", len(tasks))
    return {"plan": tasks, "error_context": "", "planner_duration_ms": planner_ms}


async def executor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute one wave of ready tasks via asyncio.gather.

    A task is "ready" when all its dependencies are already in results.
    LLM tools: agent.run(state=state, plan_task=task).
    Function tools (if any): agent.call(task['params']).

    If the planner produced no tasks (empty plan), there is nothing to run; return
    no state updates so routing sends the run straight to the response node.
    """
    plan = state.get("plan") or []
    if not plan:
        logger.info("Executor: empty plan — skipping tools; routing will go to responder")
        return {}

    results = state.get("results") or {}
    cfg = load_config()
    timeout = cfg["executor"]["tool_timeout_seconds"]

    completed_ids = set(results.keys())
    ready = [
        t for t in plan
        if t["id"] not in completed_ids
        and all(dep in completed_ids for dep in t.get("depends_on", []))
    ]

    if not ready:
        return {}

    existing_trace = state.get("trace") or []
    seen_waves = {e.get("wave", 0) for e in existing_trace if isinstance(e, dict)}
    wave = (max(seen_waves) + 1) if seen_waves else 1

    concurrency_cap = cfg["executor"].get("max_parallel_tools", len(ready))
    sem = asyncio.Semaphore(concurrency_cap)

    async def _run_one(task: dict) -> tuple[str, dict | None, dict]:
        tid = task["id"]
        agent = registry.get(task["agent"])
        async with sem:
            t0 = time.perf_counter()
            try:
                if task["type"] == "llm":
                    res = await asyncio.wait_for(
                        agent.run(state=state, plan_task=task),
                        timeout=timeout,
                    )
                else:
                    res = await asyncio.wait_for(
                        agent.call(task["params"]),
                        timeout=timeout,
                    )
                duration_ms = int((time.perf_counter() - t0) * 1000)
                trace = {
                    "task_id": tid, "agent": task["agent"],
                    "status": "ok", "result": res,
                    "duration_ms": duration_ms, "wave": wave,
                }
                return tid, res, trace
            except Exception as exc:
                duration_ms = int((time.perf_counter() - t0) * 1000)
                logger.exception(
                    "Task %s (%s) failed after tool-level retries",
                    tid,
                    task["agent"],
                )
                ufe = isinstance(exc, UserFacingToolError)
                trace = {
                    "task_id": tid, "agent": task["agent"],
                    "status": "error", "error": str(exc),
                    "user_facing": ufe,
                    "duration_ms": duration_ms, "wave": wave,
                }
                return tid, None, trace

    outcomes = await asyncio.gather(
        *[_run_one(t) for t in ready], return_exceptions=True
    )

    new_results: dict[str, Any] = {}
    new_trace: list[dict] = []
    errors: list[str] = []
    user_facing_parts: list[str] = []

    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            errors.append(str(outcome))
            continue
        tid, res, trace_entry = outcome
        new_trace.append(trace_entry)
        if res is not None:
            new_results[tid] = res
        else:
            err_msg = trace_entry.get("error", f"Task {tid} failed")
            errors.append(err_msg)
            if trace_entry.get("user_facing"):
                user_facing_parts.append(str(err_msg))

    update: dict[str, Any] = {"results": new_results, "trace": new_trace}
    if errors:
        update["error_context"] = "; ".join(errors)
    else:
        update["error_context"] = ""

    update["user_facing_error"] = (
        "; ".join(user_facing_parts) if user_facing_parts else ""
    )

    return update


def route_after_executor(state: dict[str, Any]) -> str:
    """Routing function for the conditional edge after executor_node.

    Returns one of: "continue", "fail", "done". Tool LLM recovery (at most one
    pass after execution failure) is inside each tool (BaseToolAgent); the graph
    does not re-run the planner on errors.

    Empty plan (no tools) → "done" immediately so the graph reaches the responder
    without looping the executor.
    """
    if state.get("error_context"):
        return "fail"

    plan = state.get("plan") or []
    if not plan:
        return "done"

    results = state.get("results") or {}
    completed = set(results.keys())
    if any(t["id"] not in completed for t in plan):
        return "continue"

    return "done"


async def mark_failure_node(state: dict[str, Any]) -> dict[str, Any]:
    """Set failure_flag before routing to response_node."""
    return {"failure_flag": True}


async def response_node(state: dict[str, Any]) -> dict[str, Any]:
    """Invoke responder LLM to synthesize a natural language answer.

    When failure_flag is set, logs internal error details and asks the responder
    for a user-safe apology without exposing technical messages.
    """
    llm = build_llm("responder")
    cfg = load_config()

    if state.get("failure_flag"):
        internal = (state.get("error_context") or "").strip() or "Unknown failure"
        logger.error(
            "Execution failed (details not shown to user): %s",
            internal,
        )
        resp_mem = build_responder_memory_block(
            user_key_facts=(state.get("user_key_facts") or "").strip(),
            context_summary=(state.get("context_summary") or "").strip(),
        ).strip()
        mem_line = f"\n\n{resp_mem}" if resp_mem else ""
        ufe = (state.get("user_facing_error") or "").strip()
        if ufe:
            content = (
                f"User message: {state['task']}{mem_line}\n\n"
                "The tools could not complete this request. The following plain-language "
                "reason is safe to share with the user (rephrase it naturally; do not add "
                "stack traces or internal IDs):\n"
                f"{ufe}\n\n"
                "Write a short, helpful reply that explains this in friendly terms and, "
                "if relevant, what they could change. Do not quote raw error codes."
            )
        else:
            content = (
                f"User message: {state['task']}{mem_line}\n\n"
                "The tools could not complete this request successfully (details are omitted here).\n\n"
                "Write a short, polite message explaining we could not produce the answer they wanted. "
                "Do not quote error codes, stack traces, or internal system messages. "
                "Suggest they rephrase or try again later."
            )
    else:
        parts = [f"User message: {state['task']}"]
        resp_mem = build_responder_memory_block(
            user_key_facts=(state.get("user_key_facts") or "").strip(),
            context_summary=(state.get("context_summary") or "").strip(),
        ).strip()
        if resp_mem:
            parts.append(resp_mem)
        parts.append(
            state.get("responder_tool_context")
            or "Tool results: (none — no tools were executed)"
        )
        content = "\n\n".join(parts)

    messages = [
        SystemMessage(content=RESPONDER_SYSTEM),
        HumanMessage(content=content),
    ]

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        llm.ainvoke(messages),
        timeout=cfg["executor"]["tool_timeout_seconds"],
    )
    responder_ms = int((time.perf_counter() - t0) * 1000)
    record_llm_call("responder", result, messages=messages, model=llm.model_name)

    return {"response": result.content, "responder_duration_ms": responder_ms}
