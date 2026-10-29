# -*- coding: utf-8 -*-
"""工具注册表：按角色装配工具集。

安全边界在服务端：
- 买家拿不到运营工具，即使模型「想调用」也不存在于工具列表中；
- 订单归属、写操作确认、参数校验都在工具内部的服务层完成，不依赖提示词。
"""
from __future__ import annotations

from backend.services.identity import Identity
from backend.tools.after_sales import build_after_sales_tools
from backend.tools.common import calculator, get_current_time
from backend.tools.guard import guard_business_errors
from backend.tools.ops import build_ops_tools
from backend.tools.order import build_order_tools
from backend.tools.product import build_product_tools


def build_tools(identity: Identity) -> list:
    tools = list(build_product_tools(identity))
    if identity.role == "buyer":
        tools.extend(build_order_tools(identity))
        tools.extend(build_after_sales_tools(identity))
    elif identity.role == "operator":
        tools.extend(build_ops_tools(identity))
    tools.extend([calculator, get_current_time])
    return guard_business_errors(tools)


def tool_names(identity: Identity) -> list[str]:
    return [tool.name for tool in build_tools(identity)]


__all__ = ["build_tools", "tool_names"]
