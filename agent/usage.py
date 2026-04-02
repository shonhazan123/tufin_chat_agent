"""Per-invocation LLM token usage — contextvar accumulator + AIMessage extraction."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage

_invocation_usage: ContextVar["InvocationUsage | None"] = ContextVar(
    "invocation_usage", default=None
)


@dataclass
class InvocationUsage:
    """Totals and per-call log for one ``graph.ainvoke`` run."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    llm_calls: list[dict[str, Any]] = field(default_factory=list)

    def add_call(self, role: str, message: BaseMessage) -> None:
        usage = extract_token_usage(message)
        inp = usage.get("input_tokens")
        out = usage.get("output_tokens")
        if isinstance(inp, int) and inp >= 0:
            self.total_input_tokens += inp
        if isinstance(out, int) and out >= 0:
            self.total_output_tokens += out
        self.llm_calls.append(
            {
                "role": role,
                "usage": {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "total_tokens": usage.get("total_tokens"),
                },
            }
        )


def extract_token_usage(message: BaseMessage) -> dict[str, int | None]:
    """Normalize provider usage into input/output/total (may be None if unknown)."""
    meta: dict[str, Any] = {}
    raw = getattr(message, "usage_metadata", None)
    if isinstance(raw, dict) and raw:
        meta = raw
    if not meta:
        rm = getattr(message, "response_metadata", None)
        if isinstance(rm, dict):
            token_usage = rm.get("token_usage")
            if isinstance(token_usage, dict):
                meta = token_usage
            else:
                u = rm.get("usage")
                if isinstance(u, dict):
                    meta = u

    def _pick(*keys: str) -> int | None:
        for k in keys:
            v = meta.get(k)
            if isinstance(v, int) and v >= 0:
                return v
            if isinstance(v, float) and v >= 0:
                return int(v)
        return None

    inp = _pick("input_tokens", "prompt_tokens", "input_token_count")
    out = _pick("output_tokens", "completion_tokens", "output_token_count")
    tot = _pick("total_tokens", "total_token_count")
    if tot is None and inp is not None and out is not None:
        tot = inp + out
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": tot}


def reset_invocation_usage() -> InvocationUsage:
    """Start a new per-invocation accumulator (call at graph entry)."""
    u = InvocationUsage()
    _invocation_usage.set(u)
    return u


def get_invocation_usage() -> InvocationUsage | None:
    return _invocation_usage.get()


def record_llm_message(role: str, message: BaseMessage) -> None:
    """Record usage from one LLM response; no-op if no active invocation."""
    u = get_invocation_usage()
    if u is None:
        return
    u.add_call(role, message)
