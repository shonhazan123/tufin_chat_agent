"""Weather tool — LLM fills JSON only when the planner sent no params; then HTTP."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
from langchain_core.messages import HumanMessage, SystemMessage

from agent.llm import get_llm_semaphore
from agent.usage import record_llm_message
from agent.yaml_config import load_config
from agent.tools.base import (
    BaseToolAgent,
    ToolInvocation,
    ToolParamValidationError,
    ToolSpec,
    registry,
    strip_json_fence,
)

logger = logging.getLogger(__name__)

SPEC = ToolSpec(
    name="weather",
    type="llm",
    purpose="Get current weather conditions for a location.",
    output_schema={
        "temp_c": float,
        "temp_f": float,
        "condition": str,
        "city_name": str,
    },
    input_schema={
        "city": "str — place name for the forecast",
        "units": "str — 'metric' or 'imperial'",
    },
    system_prompt=(
        "## Role\n"
        "You are a **parameter specialist** for the weather tool. You produce **one JSON "
        "object** with `city` and `units` for a weather API call.\n\n"
        "## Priority order (resolve conflicts using this)\n"
        "1. **Strict JSON** — output only the required JSON object.\n"
        "2. **Schema validity** — `city` is a non-empty string; `units` is `metric` or `imperial`.\n"
        "3. **User intent** — infer the intended location and units from context.\n\n"
        "## When you run\n"
        "The planner should supply `params`. **You are invoked when those fields are "
        "missing or invalid.** Infer values from: the user request, `context_summary`, "
        "`sub_task`, and prior tool results.\n\n"
        "## Output contract\n"
        "Return **only**:\n"
        '  {"city": "<city or place name>", "units": "metric" | "imperial"}\n\n'
        "## Rules\n"
        "1. **city** — Clear, geocodable place name; prefer what the user stated.\n"
        "2. **units** — Use `metric` unless the user clearly wants Fahrenheit / US customary "
        "(then `imperial`).\n\n"
        "## Format\n"
        "Raw JSON only — no markdown fences, no commentary.\n"
    ),
    default_ttl_seconds=300,
)

WEATHER_SYSTEM = SPEC.system_prompt


def _weather_params_usable(params: dict[str, Any]) -> bool:
    city = params.get("city")
    if city is not None and (not isinstance(city, str) or not city.strip()):
        return False
    units = params.get("units")
    if units is not None:
        if not isinstance(units, str):
            return False
        if units.strip().lower() not in ("metric", "imperial"):
            return False
    return True


@registry.register(SPEC)
class WeatherAgent(BaseToolAgent):
    SYSTEM = WEATHER_SYSTEM

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
        async with get_llm_semaphore():
            params_msg = await asyncio.wait_for(
                self.llm.ainvoke([
                    SystemMessage(content=self.SYSTEM),
                    HumanMessage(content=human_content),
                ]),
                timeout=self.timeout,
            )
        record_llm_message(f"tool:{self.spec.name}", params_msg)
        raw = strip_json_fence(params_msg.content)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("JSON root must be an object")
        return parsed

    async def _tool_executor(self, inv: ToolInvocation) -> dict[str, Any]:
        if not inv.planner_params:
            params = await self._llm_json_params_once(inv)
        else:
            params = dict(inv.planner_params)

        if not _weather_params_usable(params):
            raise ToolParamValidationError(
                "weather: invalid city/units in planner or tool LLM output"
            )

        return await self._fetch_weather(params)

    async def _fetch_weather(self, params: dict[str, Any]) -> dict[str, Any]:
        city = params.get("city", "London")
        cfg = load_config()
        tool_cfg = cfg["tools"]["weather"]
        api_key = tool_cfg.get("api_key", "")
        timeout = tool_cfg.get("timeout_seconds", 5)

        if api_key:
            return await self._call_weatherapi(city, api_key, timeout)
        return await self._call_wttr(city, timeout)

    async def _call_weatherapi(
        self, city: str, api_key: str, timeout: int
    ) -> dict[str, Any]:
        """Call WeatherAPI.com with API key."""
        url = "https://api.weatherapi.com/v1/current.json"
        req_params = {"key": api_key, "q": city, "aqi": "no"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=req_params, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        current = data["current"]
        return {
            "temp_c": current["temp_c"],
            "temp_f": current["temp_f"],
            "condition": current["condition"]["text"],
            "city_name": data["location"]["name"],
        }

    async def _call_wttr(self, city: str, timeout: int) -> dict[str, Any]:
        """Fallback: wttr.in free API (no key needed)."""
        url = f"https://wttr.in/{city}"
        req_params = {"format": "j1"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=req_params, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        current = data["current_condition"][0]
        temp_c = float(current["temp_C"])
        temp_f = float(current["temp_F"])
        condition = current["weatherDesc"][0]["value"]
        area = data["nearest_area"][0]["areaName"][0]["value"]
        return {
            "temp_c": temp_c,
            "temp_f": temp_f,
            "condition": condition,
            "city_name": area,
        }
