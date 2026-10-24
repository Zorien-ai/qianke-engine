"""安全计算器：Python 领域函数 + JSON Tool Adapter。"""
from __future__ import annotations

import ast
import operator
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from rag_demo.agent.tool import ToolResult

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class CalculatorInput(BaseModel):
    """calculator 的 JSON Schema。"""

    model_config = ConfigDict(extra="forbid")
    expression: str = Field(..., description="只含数字、括号与 + - * / // % ** 的算术表达式")


def calculate(expression: str) -> float:
    """领域逻辑：安全 AST 求值，绝不使用 eval()。"""
    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"不支持 {type(node).__name__}")

    tree = ast.parse((expression or "").strip(), mode="eval")
    return _eval(tree)


def _calculator_adapter(expression: str) -> dict[str, Any]:
    """Tool Adapter：Python 异常 -> 统一 JSON Error Code。"""
    try:
        result = calculate(expression)
        return ToolResult.success(expression=expression, result=result).dump()
    except ZeroDivisionError:
        return ToolResult.failure(
            "DIVISION_BY_ZERO", "division by zero", {"expression": expression}
        ).dump()
    except (SyntaxError, ValueError, TypeError) as exc:
        return ToolResult.failure(
            "INVALID_EXPRESSION", f"{type(exc).__name__}: {exc}", {"expression": expression}
        ).dump()


@tool(args_schema=CalculatorInput)
def calculator(expression: str) -> dict[str, Any]:
    """计算数学表达式，例如占比、增长率、金额汇总。

    只支持数字与 + - * / // % ** 和括号；禁止变量、函数、导入和属性访问。
    """
    return _calculator_adapter(expression)
