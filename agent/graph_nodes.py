"""Graph nodes — planner, executor, failure marker, response, and routing."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.llm import build_llm
from agent.prompts import RESPONDER_SYSTEM, build_planner_prompt
from agent.tools.base import registry
from agent.yaml_config import load_config

logger = logging.getLogger(__name__)


async def planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """Invoke planner LLM to produce a JSON execution plan.

    On retry, includes error_context so the planner can adjust its approach.
    Always clears error_context after reading it.
    """
    llm = build_llm("planner")
    system_prompt = build_planner_prompt()
    cfg = load_config()

    parts = [f"Task: {state['task']}"]
    if state.get("context_summary"):
        parts.append(f"[Conversation context]\n{state['context_summary']}")
    if state.get("error_context"):
        parts.append(
            f"[Previous attempt failed]\n{state['error_context']}\n"
            "Please create a revised plan that avoids the error above."
        )

    result = await asyncio.wait_for(
        llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content="\n\n".join(parts)),
        ]),
        timeout=cfg["executor"]["tool_timeout_seconds"],
    )

    text = result.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Planner returned invalid JSON: %s", exc)
        return {"error_context": f"Planner JSON parse error: {exc}", "retry_count": 1}

    tasks = raw.get("tasks", raw) if isinstance(raw, dict) else raw
    logger.info("Planner produced %d task(s)", len(tasks))
    return {"plan": tasks, "error_context": ""}


async def executor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute one wave of ready tasks via asyncio.gather.

    A task is "ready" when all its dependencies are already in results.
    LLM tools: agent.run(..., planner_params=task['params'], context_summary=...).
    Function tools (if any): agent.call(task['params']).
    """
    plan = state["plan"]
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

    concurrency_cap = cfg["executor"].get("max_parallel_tools", len(ready))
    sem = asyncio.Semaphore(concurrency_cap)

    async def _run_one(task: dict) -> tuple[str, dict | None, dict]:
        tid = task["id"]
        agent = registry.get(task["agent"])
        async with sem:
            try:
                if task["type"] == "llm":
                    res = await asyncio.wait_for(
                        agent.run(
                            user_msg=state["task"],
                            sub_task=task.get("sub_task") or "",
                            prior_results=results,
                            planner_params=task.get("params"),
                            context_summary=state.get("context_summary") or "",
                        ),
                        timeout=timeout,
                    )
                else:
                    res = await asyncio.wait_for(
                        agent.call(task["params"]),
                        timeout=timeout,
                    )
                trace = {"task_id": tid, "agent": task["agent"], "status": "ok", "result": res}
                return tid, res, trace
            except Exception as exc:
                logger.warning("Task %s (%s) failed: %s", tid, task["agent"], exc)
                trace = {"task_id": tid, "agent": task["agent"], "status": "error", "error": str(exc)}
                return tid, None, trace

    outcomes = await asyncio.gather(
        *[_run_one(t) for t in ready], return_exceptions=True
    )

    new_results: dict[str, Any] = {}
    new_trace: list[dict] = []
    errors: list[str] = []

    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            errors.append(str(outcome))
            continue
        tid, res, trace_entry = outcome
        new_trace.append(trace_entry)
        if res is not None:
            new_results[tid] = res
        else:
            errors.append(trace_entry.get("error", f"Task {tid} failed"))

    update: dict[str, Any] = {"results": new_results, "trace": new_trace}
    if errors:
        update["error_context"] = "; ".join(errors)
        update["retry_count"] = 1
    else:
        update["error_context"] = ""

    return update


def route_after_executor(state: dict[str, Any]) -> str:
    """Routing function for the conditional edge after executor_node.

    Returns one of: "continue", "retry", "fail", "done".
    """
    if state.get("error_context"):
        max_retries = load_config()["graph"]["max_retries"]
        if state.get("retry_count", 0) < max_retries:
            return "retry"
        return "fail"

    plan = state.get("plan") or []
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

    When failure_flag is set, produces a polite error message instead.
    """
    llm = build_llm("responder")
    cfg = load_config()

    if state.get("failure_flag"):
        content = (
            f"Task: {state['task']}\n\n"
            f"The system could not complete this task after multiple retries.\n"
            f"Last error: {state.get('error_context', 'Unknown')}\n\n"
            "Generate a polite apology and suggest the user rephrase or try again."
        )
    else:
        content = (
            f"Task: {state['task']}\n\n"
            f"Tool results:\n{json.dumps(state.get('results') or {}, indent=2, default=str)}\n\n"
            f"Execution trace:\n{json.dumps(state.get('trace') or [], indent=2, default=str)}"
        )

    result = await asyncio.wait_for(
        llm.ainvoke([
            SystemMessage(content=RESPONDER_SYSTEM),
            HumanMessage(content=content),
        ]),
        timeout=cfg["executor"]["tool_timeout_seconds"],
    )

    return {"response": result.content}
