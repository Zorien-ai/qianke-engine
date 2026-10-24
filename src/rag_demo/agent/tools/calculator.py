"""安全计算器：Python 领域函数 + JSON Tool Adapter。

安全边界（全部在 AST 求值前/中生效）：
- 表达式长度上限
- AST 节点数量上限
- 运算符白名单
- 数值绝对值上限
- 幂指数上限
- 结果 finite / 范围检查

不使用 eval()，也不允许变量、函数、属性访问和导入。
"""
from __future__ import annotations

import ast
import math
import operator
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from rag_demo.agent.tool import ToolResult

MAX_EXPRESSION_LENGTH = 200
MAX_AST_NODES = 50
MAX_ABS_OPERAND = 10**12
MAX_EXPONENT = 20
MAX_ABS_RESULT = 10**15

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
    expression: str = Field(
        ...,
        description="只含数字、括号与 + - * / // % ** 的算术表达式",
    )


def _check_number(value: Any, *, limit: float = MAX_ABS_OPERAND) -> int | float:
    """数值类型、finite 与绝对值检查。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("只允许数字常量")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("数值不是 finite")
    if abs(value) > limit:
        raise ValueError(f"数值超出安全范围（>{limit:g}）")
    return value


def _check_result(value: int | float) -> int | float:
    return _check_number(value, limit=MAX_ABS_RESULT)


def calculate(expression: str) -> int | float:
    """领域逻辑：长度/节点/operator/数值范围受限的安全 AST 求值。"""
    text = (expression or "").strip()
    if not text:
        raise ValueError("表达式为空")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"表达式过长（>{MAX_EXPRESSION_LENGTH} 字符）")

    tree = ast.parse(text, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValueError(f"表达式节点过多（>{MAX_AST_NODES}）")

    def _eval(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("只允许数字常量")
            return _check_number(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Pow):
                if abs(right) > MAX_EXPONENT:
                    raise ValueError(f"幂指数超出安全范围（>{MAX_EXPONENT}）")
                try:
                    result = operator.pow(left, right)
                except OverflowError as exc:
                    raise ValueError("幂运算结果溢出") from exc
                return _check_result(result)
            try:
                result = _BIN_OPS[type(node.op)](left, right)
            except ZeroDivisionError:
                raise
            except (OverflowError, ArithmeticError) as exc:
                raise ValueError(f"算术运算失败: {exc}") from exc
            return _check_result(result)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _check_result(_UNARY_OPS[type(node.op)](_eval(node.operand)))
        raise ValueError(f"不支持 {type(node).__name__}")

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
    except (SyntaxError, ValueError, TypeError, OverflowError) as exc:
        return ToolResult.failure(
            "INVALID_EXPRESSION",
            f"{type(exc).__name__}: {exc}",
            {"expression": expression},
        ).dump()


@tool(args_schema=CalculatorInput)
def calculator(expression: str) -> dict[str, Any]:
    """计算数学表达式，例如占比、增长率、金额汇总。

    只支持数字与 + - * / // % ** 和括号；禁止变量、函数、导入和属性访问。
    超过长度/节点/数值/指数安全上限时返回 INVALID_EXPRESSION。
    """
    return _calculator_adapter(expression)
