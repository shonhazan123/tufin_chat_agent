"""Calculator tool — LLM fills expression only when missing; then safe eval."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import math
import operator
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.llm import get_llm_semaphore
from agent.tokens import record_llm_call
from agent.tools.base import (
    BaseToolAgent,
    ToolInvocation,
    ToolParamValidationError,
    ToolSpec,
    UserFacingToolError,
    registry,
    strip_json_fence,
)

logger = logging.getLogger(__name__)

SPEC = ToolSpec(
    name="calculator",
    type="llm",
    purpose="Evaluate a mathematical expression and return the numeric result.",
    output_schema={"result": float},
    input_schema={
        "expression": (
            "str — single expression: numbers, + - * /, ** or ^ for powers, parentheses, "
            "constants pi and e, functions sqrt, cbrt, abs, round, sin, cos, tan, log, "
            "log10, ceil, floor"
        ),
    },
    system_prompt=(
        "## Role\n"
        "You are a **parameter specialist** for the calculator tool. You emit **one JSON "
        "object** that sets the mathematical `expression` string for a safe evaluator.\n\n"
        "## Priority order (resolve conflicts using this)\n"
        "1. **Strict JSON** — output only the required JSON object.\n"
        "2. **Allowed syntax** — expression must obey the permitted grammar.\n"
        "3. **User intent** — infer the intended expression from context.\n\n"
        "## When you run\n"
        "The planner normally fills `params.expression`. **You are invoked only when that "
        "value is missing or unusable.** Then infer the expression from: the user request, "
        "`context_summary`, `sub_task`, and prior tool results (given in the user message).\n\n"
        "## Output contract\n"
        "Return **only** this JSON shape (no markdown, no prose):\n"
        '  {"expression": "<single mathematical expression>"}\n\n'
        "## Expression rules\n"
        "1. **Allowed syntax** — Numbers; binary ops `+`, `-`, `*`, `/`; `**` or `^` for "
        "powers (both mean exponentiation; `^` is **not** bitwise XOR); parentheses.\n"
        "2. **Functions** — `sqrt`, `cbrt`, `abs`, `round`, `sin`, `cos`, `tan`, `log`, "
        "`log10`, `ceil`, `floor`.\n"
        "3. **Constants** — `pi`, `e` as identifiers.\n"
        "4. **Single expression** — One evaluable expression string, not multiple "
        "statements.\n\n"
        "## Format\n"
        "Raw JSON object only — no code fences, no explanation.\n"
    ),
    default_ttl_seconds=0,
)

CALCULATOR_SYSTEM = SPEC.system_prompt

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _cbrt(x: float) -> float:
    """Real cube root (negative inputs yield negative results)."""
    xf = float(x)
    return math.copysign(abs(xf) ** (1.0 / 3.0), xf)


_SAFE_FUNCS = {
    "sqrt": math.sqrt,
    "cbrt": _cbrt,
    "abs": abs,
    "round": round,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "pi": math.pi,
    "e": math.e,
    "ceil": math.ceil,
    "floor": math.floor,
}

_pool = ThreadPoolExecutor(max_workers=4)

# Collapse accidental "****" after normalizing mixed ^ and ** (e.g. "^**" → "****").
_RE_COLLAPSE_POW = re.compile(r"\*{4,}")


def _normalize_expression(expression: str) -> str:
    """Map school-style ^ to Python ** for exponentiation; trim whitespace."""
    s = expression.strip().replace("^", "**")
    s = _RE_COLLAPSE_POW.sub("**", s)
    return s


def _expression_params_valid(params: dict[str, Any]) -> bool:
    exp = params.get("expression")
    return isinstance(exp, str) and bool(str(exp).strip())


def _expression_missing(params: dict[str, Any], planner_was_empty: bool) -> bool:
    if planner_was_empty:
        return True
    exp = params.get("expression")
    if exp is None:
        return True
    if isinstance(exp, str) and not str(exp).strip():
        return True
    return False


def _safe_eval_node(node: ast.AST) -> float:
    """Recursively evaluate an AST node using only whitelisted operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        return float(_SAFE_OPS[op_type](left, right))

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval_node(node.operand)
        return float(_SAFE_OPS[op_type](operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only named function calls are allowed")
        fname = node.func.id
        if fname not in _SAFE_FUNCS:
            raise ValueError(f"Unsupported function: {fname}")
        func = _SAFE_FUNCS[fname]
        args = [_safe_eval_node(a) for a in node.args]
        return float(func(*args))

    if isinstance(node, ast.Name):
        if node.id not in _SAFE_FUNCS:
            raise ValueError(f"Unknown name: {node.id}")
        val = _SAFE_FUNCS[node.id]
        if not callable(val):
            return float(val)
        raise ValueError(f"'{node.id}' is a function — call it with parentheses")

    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def _safe_eval(expression: str) -> float:
    """Parse and evaluate a math expression using AST-based whitelisting."""
    normalized = _normalize_expression(expression)
    tree = ast.parse(normalized, mode="eval")
    return _safe_eval_node(tree)


def _map_eval_exception(exc: BaseException) -> UserFacingToolError:
    """Convert evaluator exceptions into short, user-safe messages."""
    if isinstance(exc, SyntaxError):
        return UserFacingToolError(
            "The expression could not be parsed; check parentheses and operators."
        )
    if isinstance(exc, ZeroDivisionError):
        return UserFacingToolError("Division by zero in the expression.")
    if isinstance(exc, OverflowError):
        return UserFacingToolError("A numeric overflow occurred; try smaller numbers.")
    if isinstance(exc, TypeError):
        return UserFacingToolError(
            "The expression uses invalid types for the operators or functions allowed here."
        )
    if isinstance(exc, ValueError):
        msg = str(exc)
        if msg.startswith("Unsupported function:"):
            name = msg.split(":", 1)[1].strip()
            return UserFacingToolError(
                f"This calculator does not support the function “{name}”. "
                "Use sqrt, cbrt, abs, round, sin, cos, tan, log, log10, ceil, or floor."
            )
        if msg.startswith("Unsupported operator:"):
            return UserFacingToolError(
                "This expression uses an operator that is not supported "
                "(use +, -, *, /, ** or ^ for powers)."
            )
        if msg.startswith("Unsupported unary operator:"):
            return UserFacingToolError(
                "This expression uses a unary operator that is not supported."
            )
        if msg.startswith("Unknown name:"):
            return UserFacingToolError(
                "The expression contains a name that is not allowed "
                "(only pi, e, and the listed functions are supported)."
            )
        if "function" in msg.lower() and "parentheses" in msg.lower():
            return UserFacingToolError(msg)
        if msg.startswith("Unsupported expression node:"):
            return UserFacingToolError(
                "Part of the expression is not supported by this calculator."
            )
        if msg.startswith("Only named function calls"):
            return UserFacingToolError(
                "Only simple function calls (e.g. sqrt(x)) are allowed in this expression."
            )
        return UserFacingToolError(
            "The expression could not be evaluated with the rules this calculator allows."
        )
    return UserFacingToolError(
        "The expression could not be evaluated. Use numbers, standard operators, "
        "and the allowed functions only."
    )


@registry.register(SPEC)
class CalculatorAgent(BaseToolAgent):
    SYSTEM = CALCULATOR_SYSTEM

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
        async with get_llm_semaphore():
            params_msg = await asyncio.wait_for(
                self.llm.ainvoke(messages),
                timeout=self.timeout,
            )
        record_llm_call(f"tool:{self.spec.name}", params_msg, messages=messages, model=self.llm.model_name)
        raw = strip_json_fence(params_msg.content)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("JSON root must be an object")
        return parsed

    async def _tool_executor(self, inv: ToolInvocation) -> dict[str, Any]:
        planner_empty = not inv.planner_params
        params = dict(inv.planner_params)

        if _expression_missing(params, planner_empty):
            params = await self._llm_json_params_once(inv)
        elif not _expression_params_valid(params):
            raise ToolParamValidationError(
                "calculator: 'expression' must be a non-empty string"
            )

        if not _expression_params_valid(params):
            raise ToolParamValidationError(
                "calculator: tool LLM did not return a valid expression"
            )

        return await self._eval_expression(params)

    async def _eval_expression(self, params: dict[str, Any]) -> dict[str, Any]:
        expression = str(params.get("expression", "")).strip()
        if not expression:
            raise UserFacingToolError("No expression was provided to evaluate.")
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(_pool, _safe_eval, expression)
        except UserFacingToolError:
            raise
        except Exception as exc:
            raise _map_eval_exception(exc) from exc
        return {"result": result}
