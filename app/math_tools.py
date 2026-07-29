"""Safe symbolic math helpers and LangChain tools for the research agent."""

from __future__ import annotations

import json
import math
from typing import Any

import sympy
from langchain_core.tools import tool
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

# Allowlisted names available to the symbolic parser (no builtins / no eval).
_ALLOWED_SYMBOLS: dict[str, Any] = {
    "x": sympy.Symbol("x"),
    "y": sympy.Symbol("y"),
    "z": sympy.Symbol("z"),
    "t": sympy.Symbol("t"),
    "n": sympy.Symbol("n", integer=True),
    "pi": sympy.pi,
    "E": sympy.E,
    "e": sympy.E,
    "oo": sympy.oo,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "asin": sympy.asin,
    "acos": sympy.acos,
    "atan": sympy.atan,
    "sinh": sympy.sinh,
    "cosh": sympy.cosh,
    "tanh": sympy.tanh,
    "exp": sympy.exp,
    "log": sympy.log,
    "ln": sympy.log,
    "sqrt": sympy.sqrt,
    "Abs": sympy.Abs,
    "abs": sympy.Abs,
    "floor": sympy.floor,
    "ceiling": sympy.ceiling,
    "Min": sympy.Min,
    "Max": sympy.Max,
    "re": sympy.re,
    "im": sympy.im,
    "conjugate": sympy.conjugate,
    "factorial": sympy.factorial,
    "binomial": sympy.binomial,
    "diff": sympy.diff,
    "integrate": sympy.integrate,
    "simplify": sympy.simplify,
    "expand": sympy.expand,
    "factor": sympy.factor,
    "Rational": sympy.Rational,
    "Integer": sympy.Integer,
    "Float": sympy.Float,
    "Pow": sympy.Pow,
    "Add": sympy.Add,
    "Mul": sympy.Mul,
}

_TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)

MAX_EXPR_CHARS = 200
MAX_PLOT_POINTS = 200
DEFAULT_PLOT_POINTS = 100
MIN_X, MAX_X = -1000.0, 1000.0
MAX_SPAN = 2000.0


class MathToolError(ValueError):
    """Raised for invalid or unsafe math tool inputs."""


def parse_math_expression(expression: str) -> sympy.Expr:
    text = (expression or "").strip()
    if not text:
        raise MathToolError("Expression is required.")
    if len(text) > MAX_EXPR_CHARS:
        raise MathToolError(f"Expression exceeds {MAX_EXPR_CHARS} characters.")
    # Reject obvious code / attribute access patterns before parsing.
    lowered = text.lower()
    for banned in ("__", "import", "lambda", "open(", "exec", "eval", "os.", "sys."):
        if banned in lowered:
            raise MathToolError("Expression contains disallowed constructs.")
    try:
        expr = parse_expr(
            text,
            local_dict=dict(_ALLOWED_SYMBOLS),
            global_dict={},
            transformations=_TRANSFORMATIONS,
            evaluate=True,
        )
    except Exception as exc:  # sympy raises varied parse errors
        raise MathToolError(f"Could not parse expression: {exc}") from exc
    if not isinstance(expr, sympy.Basic):
        raise MathToolError("Parsed value is not a symbolic expression.")
    return expr


def analyze_expression(
    expression: str,
    *,
    operation: str = "simplify",
    variable: str = "x",
) -> dict[str, Any]:
    expr = parse_math_expression(expression)
    op = (operation or "simplify").strip().lower()
    var_name = (variable or "x").strip() or "x"
    if var_name not in _ALLOWED_SYMBOLS or not isinstance(
        _ALLOWED_SYMBOLS[var_name], sympy.Symbol
    ):
        raise MathToolError(f"Variable '{var_name}' is not allowlisted.")
    var = _ALLOWED_SYMBOLS[var_name]

    if op in {"simplify", "auto"}:
        result = sympy.simplify(expr)
    elif op == "expand":
        result = sympy.expand(expr)
    elif op == "factor":
        result = sympy.factor(expr)
    elif op in {"diff", "differentiate", "derivative"}:
        result = sympy.diff(expr, var)
    elif op in {"integrate", "integral"}:
        result = sympy.integrate(expr, var)
    elif op in {"solve", "roots"}:
        result = sympy.solve(expr, var)
    elif op == "latex":
        result = expr
    else:
        raise MathToolError(
            "Unsupported operation. Use simplify, expand, factor, diff, "
            "integrate, solve, or latex."
        )

    latex = sympy.latex(result)
    return {
        "kind": "math_analysis",
        "expression": expression,
        "operation": op,
        "variable": var_name,
        "result": str(result),
        "latex": latex,
    }


def plot_expression(
    expression: str,
    *,
    x_min: float = -10.0,
    x_max: float = 10.0,
    num_points: int = DEFAULT_PLOT_POINTS,
) -> dict[str, Any]:
    if not math.isfinite(x_min) or not math.isfinite(x_max):
        raise MathToolError("x_min and x_max must be finite.")
    if x_min >= x_max:
        raise MathToolError("x_min must be less than x_max.")
    if x_min < MIN_X or x_max > MAX_X:
        raise MathToolError(f"Plot range must stay within [{MIN_X}, {MAX_X}].")
    if (x_max - x_min) > MAX_SPAN:
        raise MathToolError(f"Plot span must be at most {MAX_SPAN}.")

    points = int(num_points)
    if points < 2:
        raise MathToolError("num_points must be at least 2.")
    if points > MAX_PLOT_POINTS:
        raise MathToolError(f"num_points must be at most {MAX_PLOT_POINTS}.")

    expr = parse_math_expression(expression)
    free = {str(s) for s in expr.free_symbols}
    if free - {"x"}:
        raise MathToolError(
            "plot_function only supports univariate expressions in x "
            f"(found free symbols: {sorted(free)})."
        )
    x = _ALLOWED_SYMBOLS["x"]
    try:
        fn = sympy.lambdify(x, expr, modules=["math"])
    except Exception as exc:
        raise MathToolError(f"Could not compile expression for plotting: {exc}") from exc

    xs: list[float] = []
    ys: list[float | None] = []
    step = (x_max - x_min) / (points - 1)
    for i in range(points):
        xv = x_min + i * step
        xs.append(float(xv))
        try:
            yv = fn(xv)
            if isinstance(yv, complex):
                ys.append(None)
            else:
                yf = float(yv)
                ys.append(yf if math.isfinite(yf) else None)
        except Exception:
            ys.append(None)

    latex = sympy.latex(expr)
    return {
        "kind": "plot",
        "expression": expression,
        "latex": latex,
        "x_min": x_min,
        "x_max": x_max,
        "num_points": points,
        "x": xs,
        "y": ys,
    }


def build_math_tools():
    """Return LangChain tools for symbolic analysis and SVG-friendly plots."""

    @tool(response_format="content_and_artifact")
    def analyze_math(
        expression: str,
        operation: str = "simplify",
        variable: str = "x",
    ) -> tuple[str, dict[str, Any]]:
        """Analyze a math expression with a safe symbolic parser (simplify/diff/integrate/solve)."""
        try:
            artifact = analyze_expression(
                expression, operation=operation, variable=variable
            )
        except MathToolError as exc:
            artifact = {
                "kind": "math_analysis",
                "error": str(exc),
                "expression": expression,
            }
            return json.dumps(artifact, ensure_ascii=False), artifact
        return json.dumps(artifact, ensure_ascii=False), artifact

    @tool(response_format="content_and_artifact")
    def plot_function(
        expression: str,
        x_min: float = -10.0,
        x_max: float = 10.0,
        num_points: int = DEFAULT_PLOT_POINTS,
    ) -> tuple[str, dict[str, Any]]:
        """Sample y=f(x) into finite points + LaTeX for frontend SVG rendering (no file writes)."""
        try:
            artifact = plot_expression(
                expression,
                x_min=float(x_min),
                x_max=float(x_max),
                num_points=int(num_points),
            )
        except MathToolError as exc:
            artifact = {
                "kind": "plot",
                "error": str(exc),
                "expression": expression,
            }
            return json.dumps(artifact, ensure_ascii=False), artifact
        return json.dumps(artifact, ensure_ascii=False), artifact

    return [analyze_math, plot_function]
