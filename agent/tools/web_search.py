"""Web search tool — LLM fills query only when missing; then Tavily."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.llm import get_llm_semaphore
from agent.token_counter import count_chat_tokens
from agent.usage import record_llm_message
from agent.yaml_config import load_config
from agent.tools.base import BaseToolAgent, ToolInvocation, ToolSpec, registry, strip_json_fence

logger = logging.getLogger(__name__)

SPEC = ToolSpec(
    name="web_search",
    type="llm",
    purpose="Search the web for current information and return a summary of results.",
    output_schema={
        "query": str,
        "results": list,
        "summary": str,
    },
    input_schema={
        "query": "str — concise search query string",
    },
    system_prompt=(
        "## Role\n"
        "You are a **parameter specialist** for web search. You emit **one JSON object** "
        "with a `query` string for the search backend.\n\n"
        "## Priority order (resolve conflicts using this)\n"
        "1. **Strict JSON** — output only the required JSON object.\n"
        "2. **Query quality** — concise, specific, and relevant.\n"
        "3. **User intent** — capture the user's actual information need.\n\n"
        "## When you run\n"
        "If the planner omitted or left empty `params.query`, **infer** a focused query "
        "from: the user request, `context_summary`, `sub_task`, and prior tool results.\n\n"
        "## Output contract\n"
        "Return **only**:\n"
        '  {"query": "<concise search query>"}\n\n'
        "## Rules\n"
        "1. Prefer **specific** keywords and entities over vague filler.\n"
        "2. Keep the query **short** but sufficient to retrieve what the user needs.\n\n"
        "## Format\n"
        "Raw JSON only — no markdown fences, no commentary.\n"
    ),
    default_ttl_seconds=600,
)

WEB_SEARCH_SYSTEM = SPEC.system_prompt


def _query_params_valid(params: dict[str, Any]) -> bool:
    q = params.get("query", "")
    return isinstance(q, str) and bool(q.strip())


@registry.register(SPEC)
class WebSearchAgent(BaseToolAgent):
    SYSTEM = WEB_SEARCH_SYSTEM

    def __init__(self) -> None:
        super().__init__()
        cfg = load_config()
        tool_cfg = cfg["tools"]["web_search"]
        api_key = tool_cfg.get("api_key", "")
        if api_key:
            os.environ.setdefault("TAVILY_API_KEY", api_key)
        self.max_results: int = tool_cfg.get("max_results", 5)

    async def _llm_json_params_once(self, inv: ToolInvocation) -> dict[str, Any]:
        parts = [
            f"User request: {inv.user_msg}",
            f"Conversation context (summary): {inv.context_summary or '(none)'}",
            f"Sub-task from plan: {inv.sub_task}",
            f"Prior tool results: {json.dumps(inv.prior_results, default=str)}",
            "Reply with a single JSON object only — no markdown, no fences, "
            "no explanation outside the JSON.",
        ]
        human_content = "\n".join(parts)
        messages = [
            SystemMessage(content=self.SYSTEM),
            HumanMessage(content=human_content),
        ]
        estimated_input = count_chat_tokens(messages, model=self.llm.model_name)
        logger.info("web_search LLM call: estimated_input_tokens=%d", estimated_input)
        async with get_llm_semaphore():
            params_msg = await asyncio.wait_for(
                self.llm.ainvoke(messages),
                timeout=self.timeout,
            )
        record_llm_message(
            f"tool:{self.spec.name}", params_msg,
            model=self.llm.model_name, estimated_input_tokens=estimated_input,
        )
        raw = strip_json_fence(params_msg.content)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("JSON root must be an object")
        return parsed

    async def _tool_executor(self, inv: ToolInvocation) -> dict[str, Any]:
        pp = inv.planner_params

        if "query" in pp and not str(pp.get("query", "")).strip():
            return {"query": "", "results": [], "summary": "No query provided."}

        if not pp or "query" not in pp:
            params = await self._llm_json_params_once(inv)
        else:
            params = dict(pp)

        if not _query_params_valid(params):
            return {"query": "", "results": [], "summary": "No query provided."}

        return await self._search_tavily(params)

    async def _search_tavily(self, params: dict[str, Any]) -> dict[str, Any]:
        query = str(params.get("query", "")).strip()

        from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper

        wrapper = TavilySearchAPIWrapper(tavily_api_key=os.environ.get("TAVILY_API_KEY", ""))
        raw_results = await wrapper.results_async(query, max_results=self.max_results)

        results = []
        for r in raw_results:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:500],
            })

        summary_parts = [r.get("content", "")[:200] for r in raw_results[:3]]
        summary = " | ".join(summary_parts) if summary_parts else "No results found."

        return {
            "query": query,
            "results": results,
            "summary": summary,
        }
