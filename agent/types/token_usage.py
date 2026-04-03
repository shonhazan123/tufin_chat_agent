"""Per-invocation LLM usage accumulator (running token totals + call log)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InvocationUsage:
    """Running totals and per-call log for one ``graph.ainvoke`` run."""

    total_cached_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
