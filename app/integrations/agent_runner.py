"""Invoke LangGraph — same behavior as legacy root main.py."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from agent.yaml_config import load_config
from agent.context import conversation_context
from agent.graph import get_graph
from agent.llm import build_llm

logger = logging.getLogger(__name__)
_RECURSION_LIMIT_PER_WAVE = 3  

@dataclass
class AgentRunResult:
    final_answer: str
    trace: list[dict]
    failure_flag: bool = False


def record_assistant_and_schedule_conversation_summary(final_answer: str) -> None:
    """Append the assistant reply, then refresh the dialogue summary in the background.

    Does not block the HTTP response: summarization runs after the caller returns from
    ``run_agent_task`` (same event loop tick schedules the task; DB work and response follow).
    """
    conversation_context.add_assistant(final_answer)
    asyncio.create_task(conversation_context.summarize_async(build_llm("responder")))


async def run_agent_task(task: str) -> AgentRunResult:
    cfg = load_config()
    graph = get_graph()

    conversation_context.add_user(task)

    initial_state = {
        "task": task,
        "context_summary": conversation_context.summary,
        "plan": [],
        "results": {},
        "trace": [],
        "response": "",
        "retry_count": 0,
        "error_context": "",
        "failure_flag": False,
    }

    result = await graph.ainvoke(
        initial_state,
        config={"recursion_limit": cfg["executor"]["max_waves"] * _RECURSION_LIMIT_PER_WAVE},
    )

    answer = result.get("response", "I was unable to generate a response.")
    trace = result.get("trace", [])
    failure_flag = bool(result.get("failure_flag", False))

    record_assistant_and_schedule_conversation_summary(answer)

    return AgentRunResult(final_answer=answer, trace=trace, failure_flag=failure_flag)
