"""Transform persisted observability_json into ReasoningStep trees for the debug API."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.schemas.task_schemas import ReasoningStep
from app.types.reasoning_step_types import ReasoningNodeType, ReasoningStepStatus


def _json_pretty(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


@dataclass
class _LlmCallSnapshot:
    """Token/model/I-O slice extracted from one observability llm_calls[] entry."""

    tokens: dict[str, int | None] | None = None
    model: str | None = None
    input_text: str | None = None
    output_text: str | None = None


def _pop_llm_call_for_role(
    llm_calls: list[dict[str, Any]],
    role: str,
) -> _LlmCallSnapshot:
    """Find and remove the first llm_calls entry whose role matches."""
    for call_index, llm_call_entry in enumerate(llm_calls):
        if llm_call_entry.get("role") == role:
            token_usage = llm_call_entry.get("usage") or {}
            llm_calls.pop(call_index)
            return _LlmCallSnapshot(
                tokens={
                    "cached": token_usage.get("cached_tokens"),
                    "input": token_usage.get("input_tokens"),
                    "output": token_usage.get("output_tokens"),
                },
                model=llm_call_entry.get("model"),
                input_text=llm_call_entry.get("input_text"),
                output_text=llm_call_entry.get("output_text"),
            )
    return _LlmCallSnapshot()


def _parse_reasoning_step_status(raw_status: str) -> ReasoningStepStatus:
    try:
        return ReasoningStepStatus(raw_status)
    except ValueError:
        return ReasoningStepStatus.OK


def _build_planner_input(observability_data: dict[str, Any], task_text: str) -> str:
    """Reconstruct the structured block fed into the planner LLM."""
    context_at_start = observability_data.get("context_at_start") or {}
    sections: list[str] = []

    sections.append(f"[Task]\n{task_text}")

    context_summary = context_at_start.get("context_summary", "").strip()
    if context_summary:
        sections.append(f"[Context Summary]\n{context_summary}")

    user_key_facts = context_at_start.get("user_key_facts", "").strip()
    if user_key_facts:
        sections.append(f"[User Key Facts]\n{user_key_facts}")

    recent_messages_text = context_at_start.get("recent_messages_text", "").strip()
    if recent_messages_text:
        sections.append(f"[Recent Messages]\n{recent_messages_text}")

    return "\n\n".join(sections)


def _build_tool_input(
    plan_task: dict[str, Any],
    tool_result: dict[str, Any] | None = None,
    tool_llm_snapshot: _LlmCallSnapshot | None = None,
    parameter_extract_llm_snapshot: _LlmCallSnapshot | None = None,
) -> str:
    """Reconstruct tool debug input: planner params, dependency info, tool LLM I/O."""
    sections: list[str] = []
    sub_task_description = plan_task.get("sub_task", "")
    if sub_task_description:
        sections.append(f"[Sub-task]\n{sub_task_description}")

    planner_params = plan_task.get("params")
    if planner_params:
        sections.append(f"[Planner Params]\n{_json_pretty(planner_params)}")

    dependency_task_ids = plan_task.get("depends_on")
    if dependency_task_ids:
        sections.append(f"[Depends On]\n{', '.join(dependency_task_ids)}")

    agent_name = plan_task.get("agent", "")
    tool_type = plan_task.get("type", "")
    if agent_name or tool_type:
        sections.append(f"[Tool]\nagent: {agent_name}  type: {tool_type}")

    if tool_llm_snapshot and tool_llm_snapshot.input_text:
        sections.append(f"[Tool LLM Input]\n{tool_llm_snapshot.input_text}")
    if tool_llm_snapshot and tool_llm_snapshot.output_text:
        sections.append(f"[Tool LLM Output]\n{tool_llm_snapshot.output_text}")

    if parameter_extract_llm_snapshot and parameter_extract_llm_snapshot.input_text:
        sections.append(f"[Extract LLM Input]\n{parameter_extract_llm_snapshot.input_text}")
    if parameter_extract_llm_snapshot and parameter_extract_llm_snapshot.output_text:
        sections.append(f"[Extract LLM Output]\n{parameter_extract_llm_snapshot.output_text}")

    resolved_params = (tool_result or {}).get("_resolved_params")
    if resolved_params:
        sections.append(f"[Resolved Params]\n{_json_pretty(resolved_params)}")

    return "\n\n".join(sections) if sections else "(no input data)"


def _build_responder_input(observability_data: dict[str, Any]) -> str:
    """Reconstruct the structured context fed into the responder LLM."""
    sections: list[str] = []

    context_at_start = observability_data.get("context_at_start") or {}
    user_message = context_at_start.get("task", "").strip()
    if user_message:
        sections.append(f"[User Message]\n{user_message}")

    user_key_facts = context_at_start.get("user_key_facts", "").strip()
    if user_key_facts:
        sections.append(f"[User Key Facts]\n{user_key_facts}")

    context_summary = context_at_start.get("context_summary", "").strip()
    if context_summary:
        sections.append(f"[Context Summary]\n{context_summary}")

    tool_results = observability_data.get("results")
    if tool_results:
        sections.append(f"[Tool Results]\n{_json_pretty(tool_results)}")

    executor_trace = observability_data.get("executor_trace")
    if executor_trace:
        sections.append(f"[Execution Trace]\n{_json_pretty(executor_trace)}")

    if observability_data.get("failure_flag"):
        error_context = observability_data.get("error_context", "").strip()
        user_facing_error = observability_data.get("user_facing_error", "").strip()
        if user_facing_error:
            sections.append(f"[User-Facing Error]\n{user_facing_error}")
        elif error_context:
            sections.append(f"[Error Context]\n{error_context}")

    return "\n\n".join(sections) if sections else "(no input data)"


def build_reasoning_tree(
    observability_data: dict[str, Any],
    task_text: str,
) -> list[ReasoningStep]:
    """Ordered planner → executor waves → responder steps from observability_json."""
    steps: list[ReasoningStep] = []
    execution_plan: list[dict[str, Any]] = observability_data.get("plan") or []
    executor_trace: list[dict[str, Any]] = observability_data.get("executor_trace") or []
    tool_results_by_task_id: dict[str, Any] = observability_data.get("results") or {}
    llm_calls: list[dict[str, Any]] = list(observability_data.get("llm_calls") or [])

    plan_task_by_id: dict[str, dict[str, Any]] = {
        task["id"]: task
        for task in execution_plan
        if isinstance(task, dict) and "id" in task
    }

    planner_duration_ms = observability_data.get("planner_duration_ms")
    planner_llm_snapshot = _pop_llm_call_for_role(llm_calls, "planner")
    planner_label = (
        f"Planner ({planner_duration_ms} ms)" if planner_duration_ms is not None else "Planner"
    )

    planner_input_summary = _build_planner_input(observability_data, task_text)
    planner_output_summary = (
        _json_pretty(execution_plan) if execution_plan else "Empty plan (no tools needed)"
    )
    planner_error_context = observability_data.get("error_context", "")
    planner_step_status = (
        ReasoningStepStatus.ERROR
        if str(planner_error_context).startswith("Planner")
        else ReasoningStepStatus.OK
    )

    steps.append(
        ReasoningStep(
            id="planner",
            label=planner_label,
            node_type=ReasoningNodeType.PLANNER,
            status=planner_step_status,
            model=planner_llm_snapshot.model,
            duration_ms=planner_duration_ms,
            tokens=planner_llm_snapshot.tokens,
            input_summary=planner_input_summary,
            output_summary=planner_output_summary,
        ),
    )

    if executor_trace:
        trace_entries_by_wave_number: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for executor_trace_entry in executor_trace:
            wave_number = executor_trace_entry.get("wave", 1)
            trace_entries_by_wave_number[wave_number].append(executor_trace_entry)

        for wave_number in sorted(trace_entries_by_wave_number):
            tool_steps: list[ReasoningStep] = []
            for executor_trace_entry in trace_entries_by_wave_number[wave_number]:
                trace_task_id = executor_trace_entry.get("task_id", "?")
                agent_name = executor_trace_entry.get("agent", "unknown")
                tool_duration_ms = executor_trace_entry.get("duration_ms")
                step_label = (
                    f"{agent_name} ({tool_duration_ms} ms)"
                    if tool_duration_ms is not None
                    else agent_name
                )
                raw_tool_status = str(executor_trace_entry.get("status", "ok"))
                tool_step_status = _parse_reasoning_step_status(raw_tool_status)

                tool_llm_snapshot = _pop_llm_call_for_role(llm_calls, f"tool:{agent_name}")
                if tool_llm_snapshot.tokens is None:
                    tool_llm_snapshot = _pop_llm_call_for_role(llm_calls, agent_name)

                parameter_extract_llm_snapshot = _pop_llm_call_for_role(
                    llm_calls,
                    f"tool:{agent_name}:extract",
                )

                plan_task = plan_task_by_id.get(trace_task_id, {})
                if tool_step_status == ReasoningStepStatus.OK:
                    tool_output_payload = (
                        executor_trace_entry.get("result")
                        or tool_results_by_task_id.get(trace_task_id)
                    )
                else:
                    tool_output_payload = None

                tool_input_summary = _build_tool_input(
                    plan_task,
                    tool_output_payload,
                    tool_llm_snapshot,
                    parameter_extract_llm_snapshot,
                )

                if tool_step_status == ReasoningStepStatus.OK:
                    tool_output_summary = (
                        _json_pretty(tool_output_payload)
                        if tool_output_payload is not None
                        else "(no result)"
                    )
                else:
                    tool_output_summary = executor_trace_entry.get("error", "(unknown error)")

                tool_steps.append(
                    ReasoningStep(
                        id=str(trace_task_id),
                        label=step_label,
                        node_type=ReasoningNodeType.TOOL,
                        status=tool_step_status,
                        model=tool_llm_snapshot.model,
                        duration_ms=tool_duration_ms,
                        tokens=tool_llm_snapshot.tokens,
                        input_summary=tool_input_summary,
                        output_summary=str(tool_output_summary),
                        wave=wave_number,
                    ),
                )

            wave_total_duration_ms = sum(
                tool_step.duration_ms or 0 for tool_step in tool_steps
            )
            wave_has_error = any(
                tool_step.status == ReasoningStepStatus.ERROR for tool_step in tool_steps
            )
            steps.append(
                ReasoningStep(
                    id=f"wave_{wave_number}",
                    label=f"Executor Wave {wave_number} ({wave_total_duration_ms} ms)",
                    node_type=ReasoningNodeType.TOOL,
                    status=ReasoningStepStatus.ERROR if wave_has_error else ReasoningStepStatus.OK,
                    duration_ms=wave_total_duration_ms or None,
                    wave=wave_number,
                    children=tool_steps,
                ),
            )

    responder_duration_ms = observability_data.get("responder_duration_ms")
    responder_llm_snapshot = _pop_llm_call_for_role(llm_calls, "responder")
    responder_label = (
        f"Responder ({responder_duration_ms} ms)"
        if responder_duration_ms is not None
        else "Responder"
    )
    responder_input_summary = _build_responder_input(observability_data)
    final_answer_text = observability_data.get("response", "")
    responder_step_status = (
        ReasoningStepStatus.ERROR
        if observability_data.get("failure_flag")
        else ReasoningStepStatus.OK
    )

    steps.append(
        ReasoningStep(
            id="responder",
            label=responder_label,
            node_type=ReasoningNodeType.RESPONDER,
            status=responder_step_status,
            model=responder_llm_snapshot.model,
            duration_ms=responder_duration_ms,
            tokens=responder_llm_snapshot.tokens,
            input_summary=responder_input_summary,
            output_summary=final_answer_text or None,
        ),
    )

    return steps
