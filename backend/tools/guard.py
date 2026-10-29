# -*- coding: utf-8 -*-
"""把可预期的业务异常转换成模型能读懂的工具结果。

越权、订单不存在、参数不合法等都属于业务结果，而不是系统故障。
如果直接向上冒泡，整条 SSE 流会中断，用户只看到一个错误码。
这里统一转成 ToolException，由 LangChain 的 handle_tool_error 机制
包装成 ToolMessage 交还给模型，让模型如实解释，而不是编造成功。
"""
from __future__ import annotations

from functools import wraps

from langchain_core.tools import ToolException

from backend.core.errors import AppError


def _message(exc: AppError) -> str:
    return f"工具执行失败：{exc.message}。请如实告知用户，不要编造成功结果。"


def guard_business_errors(tools: list) -> list:
    for item in tools:
        if item.func is None or getattr(item.func, "_shop_guarded", False):
            continue

        @wraps(item.func)
        def guarded(*args, __func=item.func, **kwargs):
            try:
                return __func(*args, **kwargs)
            except AppError as exc:
                raise ToolException(_message(exc)) from exc

        guarded._shop_guarded = True
        item.func = guarded
        item.handle_tool_error = True
    return tools
