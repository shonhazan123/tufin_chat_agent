"""Weather tool — LLM fills JSON only when the planner sent no params; then HTTP."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from agent.config_loader import load_config
from agent.tools.tool_base_classes import (
    BaseToolAgent,
    ToolInvocation,
    ToolParamValidationError,
    ToolSpec,
    registry,
)

logger = logging.getLogger(__name__)

TOOL_SPEC = ToolSpec(
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
        "missing, invalid, or need to be extracted from a prior tool's output.** Infer "
        "values from: the user request, `context_summary`, `sub_task`, and prior tool "
        "results.\n\n"
        "## Disambiguation (critical)\n"
        "Prior tool results may contain **multiple conflicting values**. Read the "
        "**user request** to identify the intended entity. Prefer the consensus value "
        "across sources. Never pick the first result blindly.\n\n"
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


@registry.register(TOOL_SPEC)
class WeatherAgent(BaseToolAgent):
    async def _tool_executor(self, tool_invocation: ToolInvocation) -> dict[str, Any]:
        params = dict(tool_invocation.planner_params)

        if tool_invocation.has_dependencies or not _weather_params_usable(params):
            params = await self._invoke_parameter_specialist_llm(tool_invocation)

        if not _weather_params_usable(params):
            raise ToolParamValidationError(
                "weather: invalid city/units in planner or tool LLM output"
            )

        return await self._fetch_weather(params)

    async def _fetch_weather(self, params: dict[str, Any]) -> dict[str, Any]:
        city = params.get("city", "London")
        config = load_config()
        tool_config = config["tools"]["weather"]
        api_key = tool_config.get("api_key", "")
        timeout_seconds = tool_config.get("timeout_seconds", 5)

        if api_key:
            return await self._call_weatherapi(city, api_key, timeout_seconds)
        return await self._call_wttr(city, timeout_seconds)

    async def _call_weatherapi(
        self, city: str, api_key: str, timeout_seconds: int
    ) -> dict[str, Any]:
        """Call WeatherAPI.com with API key."""
        url = "https://api.weatherapi.com/v1/current.json"
        request_params = {"key": api_key, "q": city, "aqi": "no"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=request_params, timeout=aiohttp.ClientTimeout(total=timeout_seconds)
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

    async def _call_wttr(self, city: str, timeout_seconds: int) -> dict[str, Any]:
        """Fallback: wttr.in free API (no key needed)."""
        url = f"https://wttr.in/{city}"
        request_params = {"format": "j1"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=request_params, timeout=aiohttp.ClientTimeout(total=timeout_seconds)
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
