"""Web search tool — LLM fills query only when missing; then Tavily."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.config_loader import load_config
from agent.llm_provider_factory import get_llm_semaphore
from agent.token_usage_tracker import record_llm_call
from agent.tools.tool_base_classes import (
    BaseToolAgent,
    ToolInvocation,
    ToolSpec,
    registry,
    strip_json_fence,
)

logger = logging.getLogger(__name__)

TOOL_SPEC = ToolSpec(
    name="web_search",
    type="llm",
    purpose="Search the web for current information and return a summary of results.",
    output_schema={
        "query": str,
        "answer": str,
        "sources": list,
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
        "If the planner omitted or left empty `params.query`, or this task depends on "
        "prior tools, **infer** a focused query from: the user request, `context_summary`, "
        "`sub_task`, and prior tool results.\n\n"
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

EXTRACT_SYSTEM = (
    "## Role\n"
    "You are a **search result analyst**. Given raw web search results and the user's "
    "question, you extract the **single most relevant answer**.\n\n"
    "## Priority order\n"
    "1. **Accuracy** — only state facts supported by the search results.\n"
    "2. **Relevance** — answer exactly what the user asked, nothing more.\n"
    "3. **Disambiguation** — if results contain conflicting data (e.g. distances to "
    "different cities with the same name), identify which matches the user's intent "
    "by checking context clues (country, airport codes, coordinates). Prefer the "
    "consensus/majority value. Ignore outliers for wrong entities.\n"
    "4. **Conciseness** — keep the answer short and factual.\n\n"
    "## Output contract\n"
    "Return **only** a JSON object:\n"
    '  {"answer": "<concise factual answer with key numbers/facts>"}\n\n'
    "## Rules\n"
    "1. Include the specific **numbers, units, and facts** the user asked for.\n"
    "2. If the user asked for a numeric value, state it clearly "
    "(e.g. 'The distance is approximately 3,459 miles (5,567 km).').\n"
    "3. Do NOT include raw URLs, HTML, or metadata.\n"
    "4. If no relevant answer can be found, say so.\n\n"
    "## Format\n"
    "Raw JSON only — no markdown fences, no commentary.\n"
)


def _parse_answer(raw_content: str) -> str:
    """Extract the plain-text answer from the extraction LLM response.

    Handles: bare JSON, fenced JSON, double-encoded JSON, or plain text fallback.
    """
    text = strip_json_fence(raw_content).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            val = parsed.get("answer", text)
            if isinstance(val, str):
                try:
                    inner = json.loads(val)
                    if isinstance(inner, dict) and "answer" in inner:
                        return str(inner["answer"])
                except (json.JSONDecodeError, TypeError):
                    pass
                return val
        return text
    except json.JSONDecodeError:
        return text


def _query_params_valid(params: dict[str, Any]) -> bool:
    query_value = params.get("query", "")
    return isinstance(query_value, str) and bool(query_value.strip())


@registry.register(TOOL_SPEC)
class WebSearchAgent(BaseToolAgent):
    def __init__(self) -> None:
        super().__init__()
        config = load_config()
        tool_config = config["tools"]["web_search"]
        api_key = tool_config.get("api_key", "")
        if api_key:
            os.environ.setdefault("TAVILY_API_KEY", api_key)
        self.max_results: int = tool_config.get("max_results", 5)

    async def _tool_executor(self, tool_invocation: ToolInvocation) -> dict[str, Any]:
        params = dict(tool_invocation.planner_params)

        if tool_invocation.has_dependencies or not _query_params_valid(params):
            params = await self._invoke_parameter_specialist_llm(tool_invocation)

        if not _query_params_valid(params):
            return {"query": "", "answer": "No query provided.", "sources": []}

        raw = await self._fetch_results(params)
        return await self._extract_answer(tool_invocation, params, raw)

    async def _fetch_results(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(params.get("query", "")).strip()

        from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper

        wrapper = TavilySearchAPIWrapper(tavily_api_key=os.environ.get("TAVILY_API_KEY", ""))
        raw_results = await wrapper.results_async(query, max_results=self.max_results)

        results: list[dict[str, Any]] = []
        for row in raw_results:
            results.append({
                "title": row.get("title", ""),
                "url": row.get("url", ""),
                "content": row.get("content", "")[:500],
            })
        return results

    async def _extract_answer(
        self,
        tool_invocation: ToolInvocation,
        params: dict[str, Any],
        raw_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """LLM reasoning step: read raw search results and extract the relevant answer."""
        query = str(params.get("query", "")).strip()
        sources = [{"title": row["title"], "url": row["url"]} for row in raw_results]

        results_text = "\n\n".join(
            f"[{index + 1}] {row['title']}\n{row['content']}"
            for index, row in enumerate(raw_results)
        )

        human_content = (
            f"User request: {tool_invocation.user_msg}\n"
            f"Sub-task: {tool_invocation.sub_task}\n"
            f"Search query: {query}\n\n"
            f"Search results:\n{results_text}\n\n"
            "Extract the relevant answer as JSON."
        )
        messages = [
            SystemMessage(content=EXTRACT_SYSTEM),
            HumanMessage(content=human_content),
        ]
        async with get_llm_semaphore():
            result = await asyncio.wait_for(
                self.llm.ainvoke(messages),
                timeout=self.timeout,
            )
        record_llm_call(
            f"tool:{self.spec.name}:extract",
            result,
            messages=messages,
            model=self.llm.model_name,
        )
        answer = _parse_answer(result.content)

        return {
            "query": query,
            "answer": answer,
            "sources": sources,
        }
