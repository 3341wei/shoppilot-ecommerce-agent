# -*- coding: utf-8 -*-
"""工具层：业务异常应转成模型可读的 ToolMessage，而不是中断整条流。"""
from backend.services.identity import Identity
from backend.tools import build_tools


def _call(tool, args: dict, call_id: str = "call_1"):
    return tool.invoke(
        {"name": tool.name, "args": args, "id": call_id, "type": "tool_call"}
    )


def test_forbidden_tool_error_is_returned_to_model():
    buyer = build_tools(Identity("u_buyer_001", "buyer", "s1"))
    get_order = next(tool for tool in buyer if tool.name == "get_order")

    message = _call(get_order, {"order_id": "SO20261001006"})

    assert message.status == "error"
    assert "不属于当前用户" in message.content
    assert message.artifact is None


def test_unknown_order_is_returned_to_model():
    buyer = build_tools(Identity("u_buyer_001", "buyer", "s1"))
    get_order = next(tool for tool in buyer if tool.name == "get_order")

    message = _call(get_order, {"order_id": "SO_NOT_EXIST"})

    assert message.status == "error"
    assert "订单" in message.content
