# -*- coding: utf-8 -*-
"""运营域工具（仅 operator 角色可用）。"""
from __future__ import annotations

from langchain_core.tools import tool

from backend.services import analytics
from backend.services.identity import Identity


def build_ops_tools(identity: Identity) -> list:  # noqa: ARG001 - 预留权限上下文
    @tool(
        "get_sales_overview",
        response_format="content_and_artifact",
        description=(
            "查询销售总览：GMV、已付款订单数、客单价、退款率、类目销售占比，并与上一个等长周期对比。"
            "用户问「卖得怎样/GMV/退款率/哪个类目好」时调用。"
            "start_date 和 end_date 格式 YYYY-MM-DD；不传则默认最近 30 天。"
        ),
    )
    def get_sales_overview(start_date: str = "", end_date: str = "") -> tuple[str, dict]:
        data = analytics.sales_overview(start_date or None, end_date or None)
        return analytics.metrics_text(data), {
            "card_type": "metrics",
            "data": data,
            "sources": [
                {
                    "title": "销售指标口径",
                    "source": "运营数据",
                    "snippet": data["note"],
                }
            ],
        }

    @tool(
        "get_inventory_alerts",
        response_format="content_and_artifact",
        description=(
            "查询库存预警：断货、紧急、紧张、滞销商品，并给出安全库存和补货建议。"
            "用户问「库存够不够/哪些要补货/滞销」时调用。"
        ),
    )
    def get_inventory_alerts() -> tuple[str, dict]:
        data = analytics.inventory_alerts()
        return analytics.inventory_text(data), {
            "card_type": "inventory",
            "data": data,
            "sources": [
                {"title": "库存预警规则", "source": "运营数据", "snippet": data["note"]}
            ],
        }

    return [get_sales_overview, get_inventory_alerts]
