"""Calculator tool — pure function, safe math expression evaluator."""

from __future__ import annotations

import ast
import asyncio
import math
import operator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.tools.base import BaseFunctionTool, ToolSpec, registry

SPEC = ToolSpec(
    name="calculator",
    type="function",
    purpose="Safely evaluate a mathematical expression and return the numeric result.",
    output_schema={"result": float},
    input_schema={"expression": "str — a mathematical expression (e.g. '42 * 18', 'sqrt(144)')"},
    default_ttl_seconds=0,
)

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

_SAFE_FUNCS = {
    "sqrt": math.sqrt,
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
    tree = ast.parse(expression.strip(), mode="eval")
    return _safe_eval_node(tree)


@registry.register(SPEC)
class CalculatorTool(BaseFunctionTool):

    async def call(self, params: dict[str, Any]) -> dict[str, Any]:
        expression = params["expression"]
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(_pool, _safe_eval, expression)
        return {"result": result}
