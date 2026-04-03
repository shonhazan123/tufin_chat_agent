"""Unit converter — LLM fills value/units only when planner sent no params; then convert."""

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
    name="unit_converter",
    type="llm",
    purpose="Convert a value between units (length, weight, temperature, currency).",
    output_schema={
        "result": float,
        "from_unit": str,
        "to_unit": str,
        "formula": str,
    },
    input_schema={
        "value": "float — numeric value to convert",
        "from_unit": "str — source unit (e.g. 'km', 'lb', 'celsius', 'USD')",
        "to_unit": "str — target unit (e.g. 'miles', 'kg', 'fahrenheit', 'EUR')",
    },
    system_prompt=(
        "## Role\n"
        "You are a **parameter specialist** for unit conversion. You emit **one JSON object** "
        "with `value`, `from_unit`, and `to_unit` for the conversion engine.\n\n"
        "## Priority order (resolve conflicts using this)\n"
        "1. **Strict JSON** — output only the required JSON object.\n"
        "2. **Schema validity** — include `value`, `from_unit`, `to_unit` in correct types.\n"
        "3. **User intent** — infer the most likely units/value from context.\n\n"
        "## When you run\n"
        "The planner should supply `params`. **You are invoked when fields are missing, "
        "invalid, or need to be extracted from a prior tool's output.** Infer from: the "
        "user request, `context_summary`, `sub_task`, and prior tool results.\n\n"
        "## Disambiguation (critical)\n"
        "Prior tool results often contain **multiple conflicting values**. You MUST:\n"
        "1. Read the **user request** carefully to identify the intended entities "
        "(e.g. 'London' without qualifier almost always means London, England/UK).\n"
        "2. **Count sources** — if 4 out of 5 results say ~3,450-3,470 miles and 1 says "
        "403 miles, the outlier is for a different entity. Use the consensus value.\n"
        "3. **Check context clues** — airport codes (LHR = London Heathrow), country names, "
        "coordinates — to verify which result matches the user's intent.\n"
        "4. **Never pick the first result blindly** — scan all results and choose the one "
        "matching the user's actual question.\n\n"
        "## Output contract\n"
        "Return **only**:\n"
        '  {"value": <number>, "from_unit": "<string>", "to_unit": "<string>"}\n\n'
        "## Rules\n"
        "1. **value** — Must be a **number** (int or float). Extract the numeric value "
        "from prior tool results or the user request. Never put text or sentences here.\n"
        "2. **Units** — Use **only** the short symbols the backend accepts:\n"
        "   - Length: km, miles, m, ft, cm, inches\n"
        "   - Weight: kg, lb, g, oz\n"
        "   - Temperature: celsius, fahrenheit, kelvin (or C, F, K)\n"
        "   - Currency: USD, EUR, GBP, JPY, CAD, AUD, CHF, CNY, INR, BRL, "
        "MXN, KRW, SEK, NOK, DKK, NZD, SGD, HKD, TRY, ILS\n"
        "3. **No other unit names** — Do not use full words like 'kilometers' or "
        "'pounds'; use the short forms above.\n\n"
        "## Format\n"
        "Raw JSON only — no markdown fences, no commentary.\n"
    ),
    default_ttl_seconds=60,
)

_LENGTH_CONVERSIONS = {
    ("km", "miles"): (0.621371, "{v} * 0.621371"),
    ("miles", "km"): (1.60934, "{v} * 1.60934"),
    ("m", "ft"): (3.28084, "{v} * 3.28084"),
    ("ft", "m"): (0.3048, "{v} * 0.3048"),
    ("cm", "inches"): (0.393701, "{v} * 0.393701"),
    ("inches", "cm"): (2.54, "{v} * 2.54"),
    ("m", "km"): (0.001, "{v} * 0.001"),
    ("km", "m"): (1000, "{v} * 1000"),
    ("ft", "inches"): (12, "{v} * 12"),
    ("inches", "ft"): (1 / 12, "{v} / 12"),
}

_WEIGHT_CONVERSIONS = {
    ("kg", "lb"): (2.20462, "{v} * 2.20462"),
    ("lb", "kg"): (0.453592, "{v} * 0.453592"),
    ("g", "oz"): (0.035274, "{v} * 0.035274"),
    ("oz", "g"): (28.3495, "{v} * 28.3495"),
    ("kg", "g"): (1000, "{v} * 1000"),
    ("g", "kg"): (0.001, "{v} * 0.001"),
}

_SUPPORTED_CURRENCY_CODES = {
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "BRL",
    "MXN", "KRW", "SEK", "NOK", "DKK", "NZD", "SGD", "HKD", "TRY", "ILS",
}


def _normalize_unit_symbol(unit: str) -> str:
    """Normalize unit names for lookup."""
    mapping = {
        "celsius": "C", "fahrenheit": "F", "kelvin": "K",
        "c": "C", "f": "F", "k": "K",
        "kilometer": "km", "kilometers": "km",
        "mile": "miles",
        "meter": "m", "meters": "m",
        "foot": "ft", "feet": "ft",
        "centimeter": "cm", "centimeters": "cm",
        "inch": "inches",
        "kilogram": "kg", "kilograms": "kg",
        "pound": "lb", "pounds": "lb",
        "gram": "g", "grams": "g",
        "ounce": "oz", "ounces": "oz",
    }
    lower = unit.strip().lower()
    return mapping.get(
        lower,
        unit.strip().upper() if lower in {c.lower() for c in _SUPPORTED_CURRENCY_CODES} else lower,
    )


def _unit_converter_params_valid(params: dict[str, Any]) -> bool:
    if "value" not in params:
        return False
    try:
        float(params["value"])
    except (TypeError, ValueError):
        return False
    from_unit_raw = params.get("from_unit", "")
    to_unit_raw = params.get("to_unit", "")
    if not isinstance(from_unit_raw, str) or not str(from_unit_raw).strip():
        return False
    if not isinstance(to_unit_raw, str) or not str(to_unit_raw).strip():
        return False
    return True


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> tuple[float, str]:
    """Convert between C, F, K."""
    conversions = {
        ("C", "F"): (lambda v: v * 9 / 5 + 32, "{v} * 9/5 + 32"),
        ("F", "C"): (lambda v: (v - 32) * 5 / 9, "({v} - 32) * 5/9"),
        ("C", "K"): (lambda v: v + 273.15, "{v} + 273.15"),
        ("K", "C"): (lambda v: v - 273.15, "{v} - 273.15"),
        ("F", "K"): (lambda v: (v - 32) * 5 / 9 + 273.15, "({v} - 32) * 5/9 + 273.15"),
        ("K", "F"): (lambda v: (v - 273.15) * 9 / 5 + 32, "({v} - 273.15) * 9/5 + 32"),
    }
    key = (from_unit, to_unit)
    if key not in conversions:
        raise ValueError(f"Unsupported temperature conversion: {from_unit} → {to_unit}")
    conversion_function, formula = conversions[key]
    return conversion_function(value), formula


async def _convert_currency(
    value: float, from_unit: str, to_unit: str
) -> tuple[float, str]:
    """Convert currency via exchangerate-api.com."""
    config = load_config()
    api_key = config["tools"]["unit_converter"].get("currency_api_key", "")
    if not api_key:
        raise ValueError(
            "Currency conversion requires EXCHANGE_API_KEY in .env"
        )

    url = f"https://v6.exchangerate-api.com/v6/{api_key}/pair/{from_unit}/{to_unit}/{value}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    if data.get("result") != "success":
        raise ValueError(f"Currency API error: {data.get('error-type', 'unknown')}")

    converted = data["conversion_result"]
    rate = data["conversion_rate"]
    return float(converted), f"{{v}} * {rate}"


@registry.register(TOOL_SPEC)
class UnitConverterAgent(BaseToolAgent):
    async def _tool_executor(self, tool_invocation: ToolInvocation) -> dict[str, Any]:
        params = dict(tool_invocation.planner_params)
        used_parameter_specialist_llm = False

        if tool_invocation.has_dependencies or not _unit_converter_params_valid(params):
            params = await self._invoke_parameter_specialist_llm(tool_invocation)
            used_parameter_specialist_llm = True

        if not _unit_converter_params_valid(params):
            raise ToolParamValidationError(
                "unit_converter: missing or invalid value/from_unit/to_unit"
            )

        result = await self._convert_backend(params)
        if used_parameter_specialist_llm:
            result["_resolved_params"] = params
        return result

    async def _convert_backend(self, params: dict[str, Any]) -> dict[str, Any]:
        value = float(params["value"])
        from_unit_normalized = _normalize_unit_symbol(str(params.get("from_unit", "")))
        to_unit_normalized = _normalize_unit_symbol(str(params.get("to_unit", "")))
        if not from_unit_normalized or not to_unit_normalized:
            raise ValueError("Missing 'from_unit' or 'to_unit'")

        if from_unit_normalized == to_unit_normalized:
            return {
                "result": value,
                "from_unit": from_unit_normalized,
                "to_unit": to_unit_normalized,
                "formula": "identity (same unit)",
            }

        if from_unit_normalized in ("C", "F", "K") and to_unit_normalized in ("C", "F", "K"):
            numeric_result, formula = _convert_temperature(
                value, from_unit_normalized, to_unit_normalized
            )
            return {
                "result": round(numeric_result, 4),
                "from_unit": from_unit_normalized,
                "to_unit": to_unit_normalized,
                "formula": formula.format(v=value),
            }

        if (
            from_unit_normalized in _SUPPORTED_CURRENCY_CODES
            and to_unit_normalized in _SUPPORTED_CURRENCY_CODES
        ):
            numeric_result, formula = await _convert_currency(
                value, from_unit_normalized, to_unit_normalized
            )
            return {
                "result": round(numeric_result, 4),
                "from_unit": from_unit_normalized,
                "to_unit": to_unit_normalized,
                "formula": formula.format(v=value),
            }

        for table in (_LENGTH_CONVERSIONS, _WEIGHT_CONVERSIONS):
            key = (from_unit_normalized, to_unit_normalized)
            if key in table:
                factor, formula = table[key]
                return {
                    "result": round(value * factor, 4),
                    "from_unit": from_unit_normalized,
                    "to_unit": to_unit_normalized,
                    "formula": formula.format(v=value),
                }

        raise ValueError(
            f"Unsupported conversion: {from_unit_normalized} → {to_unit_normalized}"
        )
