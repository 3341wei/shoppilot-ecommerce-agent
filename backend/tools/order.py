# -*- coding: utf-8 -*-
"""订单与物流工具（仅买家可用，服务层强制校验归属）。"""
from __future__ import annotations

from langchain_core.tools import tool

from backend.services import orders
from backend.services.identity import Identity


def build_order_tools(identity: Identity) -> list:
    @tool(
        "get_order",
        response_format="content_and_artifact",
        description=(
            "查询订单状态、商品、实付金额和下一步建议。用户提供订单号时调用。"
            "只能查询当前登录用户自己的订单；订单号格式如 SO20261001003。"
        ),
    )
    def get_order(order_id: str) -> tuple[str, dict]:
        order = orders.get_order(order_id.strip(), identity)
        return orders.order_text(order), {
            "card_type": "order",
            "data": {"order": orders.order_card(order)},
            "sources": [
                {
                    "title": f"订单 {order_id}",
                    "source": "订单系统",
                    "snippet": f"状态：{order['status_label']}，实付 ¥{order['amount']:.2f}",
                }
            ],
        }

    @tool(
        "track_logistics",
        response_format="content_and_artifact",
        description=(
            "查询订单物流轨迹，并自动判断是否停滞超过 48 小时。"
            "用户问「到哪了/什么时候到/物流不动了」时调用。只能查当前用户自己的订单。"
        ),
    )
    def track_logistics(order_id: str) -> tuple[str, dict]:
        data = orders.get_logistics(order_id.strip(), identity)
        return orders.logistics_text(data), {
            "card_type": "logistics",
            "data": data,
            "sources": [
                {
                    "title": f"物流 {data['tracking_no'] or data['order_id']}",
                    "source": data["company"] or "物流系统",
                    "snippet": data["latest"]["description"] if data["latest"] else "暂无轨迹",
                }
            ],
        }

    return [get_order, track_logistics]
