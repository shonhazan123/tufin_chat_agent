"""Web search tool — LLM query extraction + Tavily API (LangChain-native)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from agent.yaml_config import load_config
from agent.tools.base import BaseToolAgent, ToolSpec, registry

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
        "You output JSON for the search API. The planner should pass 'query' in 'params'; "
        "you run when that is missing or search failed — then craft a better query from the "
        "user request, conversation summary, sub-task, prior results, and any error message.\n\n"
        "Output ONLY a JSON object with this field:\n"
        '  {"query": "<search query string>"}\n\n'
        "Rules:\n"
        "- Make the query specific and concise.\n"
        "- If prior results provide relevant context, incorporate key terms.\n"
        "- Output raw JSON only — no markdown, no explanation.\n"
    ),
    default_ttl_seconds=600,
)

WEB_SEARCH_SYSTEM = SPEC.system_prompt


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

    async def _tool_executer(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"query": "", "results": [], "summary": "No query provided."}

        from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper

        wrapper = TavilySearchAPIWrapper(tavily_api_key=os.environ.get("TAVILY_API_KEY", ""))
        raw_results = await wrapper.aresults(query, max_results=self.max_results)

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
