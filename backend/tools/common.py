# -*- coding: utf-8 -*-
"""通用工具：安全计算器、当前时间。"""
from __future__ import annotations

import ast
import operator
from datetime import datetime

from langchain_core.tools import tool

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_MAX_EXPRESSION_LENGTH = 200
_MAX_RESULT = 1e12


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        result = _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
        if abs(result) > _MAX_RESULT:
            raise ValueError("计算结果过大")
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ValueError("表达式包含不支持的运算")


@tool(description="计算算术表达式，例如 399*0.9-20。仅支持数字与 + - * / ( )。需要算价、算差价时调用。")
def calculator(expression: str) -> str:
    expression = (expression or "").strip()
    if not expression:
        return "计算错误：表达式为空"
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        return "计算错误：表达式过长"
    try:
        result = _eval_node(ast.parse(expression, mode="eval"))
        return str(int(result)) if result.is_integer() else str(round(result, 6))
    except ZeroDivisionError:
        return "计算错误：除数不能为 0"
    except (SyntaxError, ValueError) as exc:
        return f"计算错误：{exc}"


@tool(description="获取当前日期和时间。用户提到今天、昨天、上周等相对时间时调用，用于确定查询区间。")
def get_current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
