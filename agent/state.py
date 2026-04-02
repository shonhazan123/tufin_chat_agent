"""LangGraph AgentState definition with explicit reducer functions."""

from __future__ import annotations

from typing import Annotated, Any

from typing_extensions import NotRequired, TypedDict


def _merge(existing: dict, new: dict) -> dict:
    """Dict reducer: shallow-merge new keys into existing."""
    return {**existing, **new}


def _append(existing: list, new: list) -> list:
    """List reducer: concatenate new items onto existing."""
    return existing + new


class AgentState(TypedDict):
    """Full state flowing through the LangGraph execution graph.

    Reducer semantics:
    - results: merge (dict grows each executor wave)
    - trace: append (list grows each executor wave)
    - All other fields: last-write-wins (plain replacement)
    """

    task: str
    context_summary: str
    user_key_facts: str
    recent_messages_text: str
    plan: list[dict]
    results: Annotated[dict[str, Any], _merge]
    trace: Annotated[list[dict], _append]
    response: str
    error_context: str
    user_facing_error: NotRequired[str]
    failure_flag: bool
    planner_duration_ms: NotRequired[int]
    responder_duration_ms: NotRequired[int]
