"""Calculator tool — safe math evaluation via ``ast`` module."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

# Allowed binary operators
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# Allowed unary operators
_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Allowed math functions (safe subset)
_MATH_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "ln": math.log,  # alias: ln(x) == log(x)
    "log10": math.log10,
    "log2": math.log2,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
    "ceil": math.ceil,
    "floor": math.floor,
}


def _safe_eval_node(node: ast.AST) -> Any:
    """Recursively evaluate an AST node using only whitelisted operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BINOPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        return _BINOPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARYOPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval_node(node.operand)
        return _UNARYOPS[op_type](operand)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        fname = node.func.id
        if fname not in _MATH_FUNCS:
            raise ValueError(f"Unknown function: {fname}")
        func = _MATH_FUNCS[fname]
        args = [_safe_eval_node(a) for a in node.args]
        return func(*args)
    if isinstance(node, ast.Name):
        name = node.id
        if name in _MATH_FUNCS:
            val = _MATH_FUNCS[name]
            if isinstance(val, (int, float)):
                return val
        raise ValueError(f"unknown variable: {name}")
    raise ValueError(f"Unsupported expression type: {type(node).__name__}")


def safe_eval(expression: str) -> float:
    """Evaluate a math expression safely — Rust backend with Python fallback."""
    try:
        from diapason._rust_bridge import get_rust_module

        _rust = get_rust_module()
        native_result = _rust.CalculatorTool().execute(expression)
        try:
            native_float = float(native_result)
        except (TypeError, ValueError):
            # The native result includes a human-readable failure string.
            # Re-evaluate with the canonical AST path to preserve the public
            # Python exceptions and exact supported-function contract.
            pass
        else:
            # The Rust path yields inf/nan where Python raises. Fall through
            # so the AST path can raise the precise exception — "division by
            # zero" is a better thing to tell someone than "out of range".
            if math.isfinite(native_float):
                return native_float
    except (AttributeError, ImportError, RuntimeError):
        pass

    # Support ^ as the power operator (common math/calculator notation).
    expression = expression.replace("^", "**")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Syntax error in expression: {exc}") from exc
    # ZeroDivisionError is deliberately *not* caught here. Converting it to
    # ``inf`` made the caller's own "division by zero" branch unreachable, and
    # handed the model a float it reads as an answer: asked to split a bill
    # among zero people, the assistant answers "inf" rather than saying the
    # question has no answer.
    return float(_safe_eval_node(tree.body))


@ToolRegistry.register("calculator")
class CalculatorTool(BaseTool):
    """Safe math calculator using AST-based evaluation."""

    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description=(
                "Evaluate a mathematical expression safely."
                " Supports arithmetic, math functions"
                " (sqrt, log, sin, cos), and constants."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "Math expression to evaluate (e.g. '2+3*4', 'sqrt(16)')"
                        ),
                    },
                },
                "required": ["expression"],
            },
            category="math",
        )

    def execute(self, **params: Any) -> ToolResult:
        expression = params.get("expression", "")
        if not expression:
            return ToolResult(
                tool_name="calculator",
                content="No expression provided.",
                success=False,
            )
        try:
            result = safe_eval(expression)
            # Overflow and log(0) reach here as inf/nan without ever raising.
            # Neither is an answer, and both read as one: "inf" in a tool
            # result is a number as far as the model is concerned.
            if not math.isfinite(result):
                kind = "undefined (0/0)" if math.isnan(result) else "out of range"
                return ToolResult(
                    tool_name="calculator",
                    content=(
                        f"Error: the result of '{expression}' is {kind}, "
                        "not a number this can report."
                    ),
                    success=False,
                )
            return ToolResult(
                tool_name="calculator",
                content=str(result),
                success=True,
            )
        except ZeroDivisionError:
            return ToolResult(
                tool_name="calculator",
                content="Error: division by zero",
                success=False,
            )
        except (ValueError, SyntaxError, TypeError) as exc:
            return ToolResult(
                tool_name="calculator",
                content=f"Error: {exc}",
                success=False,
            )


__all__ = ["CalculatorTool", "safe_eval"]
