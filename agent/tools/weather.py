"""Weather tool — LLM-powered parameter extraction + aiohttp API call."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from agent.yaml_config import load_config
from agent.tools.base import BaseToolAgent, ToolSpec, registry

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
        "You output JSON for the weather API. The planner should pass city and units in "
        "'params'; you run when those are missing or the API call failed — then infer or "
        "correct city/units from the user request, conversation summary, sub-task, prior "
        "results, and any error message.\n\n"
        "Output ONLY a JSON object with these fields:\n"
        '  {"city": "<city name>", "units": "metric"}\n\n'
        "Rules:\n"
        "- Default units to 'metric' unless the user explicitly asks for Fahrenheit/imperial.\n"
        "- If prior results contain a city name, use it.\n"
        "- Output raw JSON only — no markdown, no explanation.\n"
    ),
    default_ttl_seconds=300,
)

WEATHER_SYSTEM = SPEC.system_prompt


@registry.register(SPEC)
class WeatherAgent(BaseToolAgent):
    SYSTEM = WEATHER_SYSTEM

    async def _tool_executer(self, params: dict[str, Any]) -> dict[str, Any]:
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
        params = {"key": api_key, "q": city, "aqi": "no"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)
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
        params = {"format": "j1"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)
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
