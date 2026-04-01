"""Unit converter tool — pure function for length, weight, temperature, currency."""

from __future__ import annotations

from typing import Any

import aiohttp

from agent.yaml_config import load_config
from agent.tools.base import BaseFunctionTool, ToolSpec, registry

SPEC = ToolSpec(
    name="unit_converter",
    type="function",
    purpose="Convert a value between units (length, weight, temperature, currency).",
    output_schema={
        "result": float,
        "from_unit": str,
        "to_unit": str,
        "formula": str,
    },
    input_schema={
        "value": "float — the numeric value to convert",
        "from_unit": "str — source unit (e.g. 'km', 'lb', 'celsius', 'USD')",
        "to_unit": "str — target unit (e.g. 'miles', 'kg', 'fahrenheit', 'EUR')",
    },
    default_ttl_seconds=60,
)

_LENGTH = {
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

_WEIGHT = {
    ("kg", "lb"): (2.20462, "{v} * 2.20462"),
    ("lb", "kg"): (0.453592, "{v} * 0.453592"),
    ("g", "oz"): (0.035274, "{v} * 0.035274"),
    ("oz", "g"): (28.3495, "{v} * 28.3495"),
    ("kg", "g"): (1000, "{v} * 1000"),
    ("g", "kg"): (0.001, "{v} * 0.001"),
}

_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "BRL",
    "MXN", "KRW", "SEK", "NOK", "DKK", "NZD", "SGD", "HKD", "TRY", "ILS",
}


def _normalize(unit: str) -> str:
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
    return mapping.get(lower, unit.strip().upper() if lower in {c.lower() for c in _CURRENCIES} else lower)


def _convert_temperature(value: float, from_u: str, to_u: str) -> tuple[float, str]:
    """Convert between C, F, K."""
    conversions = {
        ("C", "F"): (lambda v: v * 9 / 5 + 32, "{v} * 9/5 + 32"),
        ("F", "C"): (lambda v: (v - 32) * 5 / 9, "({v} - 32) * 5/9"),
        ("C", "K"): (lambda v: v + 273.15, "{v} + 273.15"),
        ("K", "C"): (lambda v: v - 273.15, "{v} - 273.15"),
        ("F", "K"): (lambda v: (v - 32) * 5 / 9 + 273.15, "({v} - 32) * 5/9 + 273.15"),
        ("K", "F"): (lambda v: (v - 273.15) * 9 / 5 + 32, "({v} - 273.15) * 9/5 + 32"),
    }
    key = (from_u, to_u)
    if key not in conversions:
        raise ValueError(f"Unsupported temperature conversion: {from_u} → {to_u}")
    fn, formula = conversions[key]
    return fn(value), formula


async def _convert_currency(
    value: float, from_u: str, to_u: str
) -> tuple[float, str]:
    """Convert currency via exchangerate-api.com."""
    cfg = load_config()
    api_key = cfg["tools"]["unit_converter"].get("currency_api_key", "")
    if not api_key:
        raise ValueError(
            "Currency conversion requires EXCHANGE_API_KEY in .env"
        )

    url = f"https://v6.exchangerate-api.com/v6/{api_key}/pair/{from_u}/{to_u}/{value}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    if data.get("result") != "success":
        raise ValueError(f"Currency API error: {data.get('error-type', 'unknown')}")

    converted = data["conversion_result"]
    rate = data["conversion_rate"]
    return float(converted), f"{{v}} * {rate}"


@registry.register(SPEC)
class UnitConverterTool(BaseFunctionTool):

    async def call(self, params: dict[str, Any]) -> dict[str, Any]:
        value = float(params["value"])
        from_unit = _normalize(params["from_unit"])
        to_unit = _normalize(params["to_unit"])

        if from_unit == to_unit:
            return {
                "result": value,
                "from_unit": from_unit,
                "to_unit": to_unit,
                "formula": "identity (same unit)",
            }

        if from_unit in ("C", "F", "K") and to_unit in ("C", "F", "K"):
            result, formula = _convert_temperature(value, from_unit, to_unit)
            return {
                "result": round(result, 4),
                "from_unit": from_unit,
                "to_unit": to_unit,
                "formula": formula.format(v=value),
            }

        if from_unit in _CURRENCIES and to_unit in _CURRENCIES:
            result, formula = await _convert_currency(value, from_unit, to_unit)
            return {
                "result": round(result, 4),
                "from_unit": from_unit,
                "to_unit": to_unit,
                "formula": formula.format(v=value),
            }

        for table in (_LENGTH, _WEIGHT):
            key = (from_unit, to_unit)
            if key in table:
                factor, formula = table[key]
                return {
                    "result": round(value * factor, 4),
                    "from_unit": from_unit,
                    "to_unit": to_unit,
                    "formula": formula.format(v=value),
                }

        raise ValueError(
            f"Unsupported conversion: {from_unit} → {to_unit}"
        )
