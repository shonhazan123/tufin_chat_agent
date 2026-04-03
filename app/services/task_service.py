"""Orchestration: SQLite task rows + Redis cache + agent runner."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent.conversation_memory import conversation_context
from agent.config_loader import load_config
from app.cache.redis_cache import RedisCache
from app.db.models import Task, TaskStatus
from app.db.task_repository import TaskRepository
from app.integrations.agent_runner import record_assistant_and_schedule_conversation_summary, run_agent_task
from app.settings import Settings
from app.schemas.task import ReasoningStep, TaskDebugResponse, TaskDetailResponse, TaskSubmitResponse

logger = logging.getLogger(__name__)


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _cache_model_hint() -> str:
    try:
        cfg = load_config()
        return str(cfg.get("agents", {}).get("responder", {}).get("model", ""))
    except Exception:
        return ""


def _observability_from_cache(cached: dict, trace: list[dict]) -> dict:
    obs = cached.get("observability_json")
    if isinstance(obs, dict) and obs:
        return obs
    return {
        "version": 1,
        "executor_trace": trace,
        "note": "legacy_cache_payload",
    }


class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        cache: RedisCache,
        settings: Settings,
    ) -> None:
        self._session = session
        self._repo = TaskRepository(session)
        self._cache = cache
        self._settings = settings

    async def create_and_run_task(self, task_text: str) -> TaskSubmitResponse:
        normalized = task_text.strip()
        task = await self._repo.create_pending(normalized)
        await self._session.commit()

        hint = _cache_model_hint()
        cache_key = self._cache.build_cache_key(normalized, hint)
        cached = await self._cache.get_cached_response(cache_key)
        if cached is not None:
            final_answer = str(cached.get("final_answer", ""))
            trace = list(cached.get("trace", []))
            obs = _observability_from_cache(cached, trace)
            latency_ms = _safe_int(cached.get("latency_ms"))
            tcached = _safe_int(cached.get("total_cached_tokens"))
            tin = _safe_int(cached.get("total_input_tokens"))
            tout = _safe_int(cached.get("total_output_tokens"))
            conversation_context.add_user(normalized)
            record_assistant_and_schedule_conversation_summary(final_answer)
            await self._repo.complete(
                task.id,
                final_answer,
                trace,
                latency_ms=latency_ms,
                total_cached_tokens=tcached,
                total_input_tokens=tin,
                total_output_tokens=tout,
                observability_json=obs,
                status=TaskStatus.cached,
            )
            await self._session.commit()
            return TaskSubmitResponse(
                task_id=task.id,
                final_answer=final_answer,
                latency_ms=latency_ms,
                total_cached_tokens=tcached,
                total_input_tokens=tin,
                total_output_tokens=tout,
            )

        await self._repo.mark_running(task.id)
        await self._session.commit()

        try:
            result = await run_agent_task(normalized)
        except Exception as exc:
            logger.exception("Agent execution failed")
            await self._session.rollback()
            await self._repo.fail(task.id, str(exc))
            await self._session.commit()
            raise

        await self._repo.complete(
            task.id,
            result.final_answer,
            result.trace,
            latency_ms=result.latency_ms,
            total_cached_tokens=result.total_cached_tokens,
            total_input_tokens=result.total_input_tokens,
            total_output_tokens=result.total_output_tokens,
            observability_json=result.observability,
            status=TaskStatus.completed,
        )
        await self._session.commit()

        await self._cache.set_cached_response(
            cache_key,
            {
                "final_answer": result.final_answer,
                "trace": result.trace,
                "latency_ms": result.latency_ms,
                "total_cached_tokens": result.total_cached_tokens,
                "total_input_tokens": result.total_input_tokens,
                "total_output_tokens": result.total_output_tokens,
                "observability_json": result.observability,
            },
            self._settings.cache_ttl_seconds,
        )

        return TaskSubmitResponse(
            task_id=task.id,
            final_answer=result.final_answer,
            latency_ms=result.latency_ms,
            total_cached_tokens=result.total_cached_tokens,
            total_input_tokens=result.total_input_tokens,
            total_output_tokens=result.total_output_tokens,
        )

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self._repo.get_by_id(task_id)

    def to_detail_response(self, task: Task) -> TaskDetailResponse:
        return TaskDetailResponse(
            task_id=task.id,
            final_answer=task.final_answer or "",
            latency_ms=task.latency_ms,
            total_cached_tokens=task.total_cached_tokens,
            total_input_tokens=task.total_input_tokens,
            total_output_tokens=task.total_output_tokens,
            observability=task.observability_json or {},
        )

    def to_debug_response(self, task: Task) -> TaskDebugResponse:
        tree = _build_reasoning_tree(task.observability_json or {}, task.task_text or "")
        return TaskDebugResponse(
            task_id=task.id,
            task_text=task.task_text or "",
            status=task.status.value if task.status else "unknown",
            final_answer=task.final_answer or "",
            error_message=task.error_message,
            created_at=task.created_at,
            completed_at=task.completed_at,
            latency_ms=task.latency_ms,
            total_cached_tokens=task.total_cached_tokens,
            total_input_tokens=task.total_input_tokens,
            total_output_tokens=task.total_output_tokens,
            reasoning_tree=tree,
        )


# ---------------------------------------------------------------------------
# Reasoning tree builder — transforms observability_json into ReasoningStep[]
# ---------------------------------------------------------------------------


def _json_pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False)


@dataclass
class _LLMCallInfo:
    tokens: dict[str, int | None] | None = None
    model: str | None = None
    input_text: str | None = None
    output_text: str | None = None


def _pop_call_for_role(
    llm_calls: list[dict[str, Any]], role: str,
) -> _LLMCallInfo:
    """Find and remove the first matching llm_call entry."""
    for i, call in enumerate(llm_calls):
        if call.get("role") == role:
            u = call.get("usage") or {}
            llm_calls.pop(i)
            return _LLMCallInfo(
                tokens={
                    "cached": u.get("cached_tokens"),
                    "input": u.get("input_tokens"),
                    "output": u.get("output_tokens"),
                },
                model=call.get("model"),
                input_text=call.get("input_text"),
                output_text=call.get("output_text"),
            )
    return _LLMCallInfo()


def _build_planner_input(obs: dict[str, Any], task_text: str) -> str:
    """Full structured input that was fed into the planner LLM."""
    ctx = obs.get("context_at_start") or {}
    sections: list[str] = []

    sections.append(f"[Task]\n{task_text}")

    summary = ctx.get("context_summary", "").strip()
    if summary:
        sections.append(f"[Context Summary]\n{summary}")

    facts = ctx.get("user_key_facts", "").strip()
    if facts:
        sections.append(f"[User Key Facts]\n{facts}")

    recent = ctx.get("recent_messages_text", "").strip()
    if recent:
        sections.append(f"[Recent Messages]\n{recent}")

    return "\n\n".join(sections)


def _build_tool_input(
    plan_task: dict[str, Any],
    tool_result: dict[str, Any] | None = None,
    tool_llm: _LLMCallInfo | None = None,
    extract_llm: _LLMCallInfo | None = None,
) -> str:
    """Full structured input for a tool, including LLM I/O for debugging.

    Shows: sub_task, planner params, dependency info, and — when the tool LLM
    was invoked — what it received as input and what it produced as output.
    """
    sections: list[str] = []
    sub = plan_task.get("sub_task", "")
    if sub:
        sections.append(f"[Sub-task]\n{sub}")

    planner_params = plan_task.get("params")
    if planner_params:
        sections.append(f"[Planner Params]\n{_json_pretty(planner_params)}")

    deps = plan_task.get("depends_on")
    if deps:
        sections.append(f"[Depends On]\n{', '.join(deps)}")

    agent = plan_task.get("agent", "")
    tool_type = plan_task.get("type", "")
    if agent or tool_type:
        sections.append(f"[Tool]\nagent: {agent}  type: {tool_type}")

    if tool_llm and tool_llm.input_text:
        sections.append(f"[Tool LLM Input]\n{tool_llm.input_text}")
    if tool_llm and tool_llm.output_text:
        sections.append(f"[Tool LLM Output]\n{tool_llm.output_text}")

    if extract_llm and extract_llm.input_text:
        sections.append(f"[Extract LLM Input]\n{extract_llm.input_text}")
    if extract_llm and extract_llm.output_text:
        sections.append(f"[Extract LLM Output]\n{extract_llm.output_text}")

    resolved = (tool_result or {}).get("_resolved_params")
    if resolved:
        sections.append(f"[Resolved Params]\n{_json_pretty(resolved)}")

    return "\n\n".join(sections) if sections else "(no input data)"


def _build_responder_input(obs: dict[str, Any]) -> str:
    """Summarize what was fed into the responder LLM."""
    sections: list[str] = []

    ctx = obs.get("context_at_start") or {}
    task = ctx.get("task", "").strip()
    if task:
        sections.append(f"[User Message]\n{task}")

    facts = ctx.get("user_key_facts", "").strip()
    if facts:
        sections.append(f"[User Key Facts]\n{facts}")

    summary = ctx.get("context_summary", "").strip()
    if summary:
        sections.append(f"[Context Summary]\n{summary}")

    results = obs.get("results")
    if results:
        sections.append(f"[Tool Results]\n{_json_pretty(results)}")

    trace = obs.get("executor_trace")
    if trace:
        sections.append(f"[Execution Trace]\n{_json_pretty(trace)}")

    if obs.get("failure_flag"):
        err = obs.get("error_context", "").strip()
        ufe = obs.get("user_facing_error", "").strip()
        if ufe:
            sections.append(f"[User-Facing Error]\n{ufe}")
        elif err:
            sections.append(f"[Error Context]\n{err}")

    return "\n\n".join(sections) if sections else "(no input data)"


def _build_reasoning_tree(obs: dict[str, Any], task_text: str) -> list[ReasoningStep]:
    """Build the ordered list of reasoning steps from observability_json."""
    steps: list[ReasoningStep] = []
    plan: list[dict] = obs.get("plan") or []
    trace: list[dict] = obs.get("executor_trace") or []
    results: dict = obs.get("results") or {}
    llm_calls: list[dict] = list(obs.get("llm_calls") or [])

    plan_by_id: dict[str, dict] = {t["id"]: t for t in plan if isinstance(t, dict) and "id" in t}

    # --- 1. Planner step ---
    planner_ms = obs.get("planner_duration_ms")
    planner_info = _pop_call_for_role(llm_calls, "planner")
    planner_label = f"Planner ({planner_ms} ms)" if planner_ms is not None else "Planner"

    planner_input = _build_planner_input(obs, task_text)
    planner_output = _json_pretty(plan) if plan else "Empty plan (no tools needed)"

    steps.append(ReasoningStep(
        id="planner",
        label=planner_label,
        node_type="planner",
        status="ok" if not obs.get("error_context", "").startswith("Planner") else "error",
        model=planner_info.model,
        duration_ms=planner_ms,
        tokens=planner_info.tokens,
        input_summary=planner_input,
        output_summary=planner_output,
    ))

    # --- 2. Executor waves ---
    if trace:
        waves: dict[int, list[dict]] = defaultdict(list)
        for entry in trace:
            w = entry.get("wave", 1)
            waves[w].append(entry)

        for wave_num in sorted(waves):
            children: list[ReasoningStep] = []
            for entry in waves[wave_num]:
                tid = entry.get("task_id", "?")
                agent_name = entry.get("agent", "unknown")
                tool_ms = entry.get("duration_ms")
                tool_label = f"{agent_name} ({tool_ms} ms)" if tool_ms is not None else agent_name
                tool_status = entry.get("status", "ok")

                tool_info = _pop_call_for_role(llm_calls, f"tool:{agent_name}")
                if tool_info.tokens is None:
                    tool_info = _pop_call_for_role(llm_calls, agent_name)

                extra_info = _pop_call_for_role(llm_calls, f"tool:{agent_name}:extract")

                plan_task = plan_by_id.get(tid, {})
                raw_result = entry.get("result") or results.get(tid) if tool_status == "ok" else None
                tool_input = _build_tool_input(plan_task, raw_result, tool_info, extra_info)

                if tool_status == "ok":
                    tool_output = _json_pretty(raw_result) if raw_result is not None else "(no result)"
                else:
                    tool_output = entry.get("error", "(unknown error)")

                children.append(ReasoningStep(
                    id=tid,
                    label=tool_label,
                    node_type="tool",
                    status=tool_status,
                    model=tool_info.model,
                    duration_ms=tool_ms,
                    tokens=tool_info.tokens,
                    input_summary=tool_input,
                    output_summary=tool_output,
                    wave=wave_num,
                ))

            wave_total_ms = sum(c.duration_ms or 0 for c in children)
            steps.append(ReasoningStep(
                id=f"wave_{wave_num}",
                label=f"Executor Wave {wave_num} ({wave_total_ms} ms)",
                node_type="tool",
                status="error" if any(c.status == "error" for c in children) else "ok",
                duration_ms=wave_total_ms or None,
                wave=wave_num,
                children=children,
            ))

    # --- 3. Responder step ---
    responder_ms = obs.get("responder_duration_ms")
    responder_info = _pop_call_for_role(llm_calls, "responder")
    responder_label = f"Responder ({responder_ms} ms)" if responder_ms is not None else "Responder"
    responder_input = _build_responder_input(obs)
    final_text = obs.get("response", "")

    steps.append(ReasoningStep(
        id="responder",
        label=responder_label,
        node_type="responder",
        status="ok" if not obs.get("failure_flag") else "error",
        model=responder_info.model,
        duration_ms=responder_ms,
        tokens=responder_info.tokens,
        input_summary=responder_input,
        output_summary=final_text or None,
    ))

    return steps
