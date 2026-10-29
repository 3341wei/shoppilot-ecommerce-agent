# -*- coding: utf-8 -*-
"""订单与物流服务。

所有对买家暴露的字段都在这里脱敏，工具层只拿得到脱敏后的数据。
"""
from __future__ import annotations

from datetime import datetime

from backend.core.errors import ForbiddenError, NotFoundError
from backend.core.security import mask_address, mask_name, mask_phone
from backend.services.db import get_conn

STATUS_LABELS = {
    "pending_payment": "待付款",
    "paid": "已付款",
    "shipped": "已发货",
    "signed": "已签收",
    "completed": "已完成",
    "refunding": "退款中",
    "cancelled": "已取消",
}

STATUS_ADVICE = {
    "pending_payment": "订单尚未付款，可在订单详情页继续支付，超时后订单会自动关闭。",
    "paid": "商家正在备货，预计 48 小时内发出。",
    "shipped": "包裹已发出，可查看物流轨迹；如需修改地址请联系客服。",
    "signed": "订单已签收。如商品有问题，可在签收后 7 天内申请售后。",
    "completed": "订单已完成。质量问题仍在保修期内，可申请维修。",
    "refunding": "退款申请处理中，请留意审核结果。",
    "cancelled": "订单已取消，如已付款会在 1-3 个工作日内原路退回。",
}


def _get_order_row(order_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return row


def _check_ownership(order: dict, identity) -> None:
    """买家只能查自己的订单；运营角色用于客服场景，可查任意订单。"""
    if identity.role == "buyer" and order["user_id"] != identity.user_id:
        raise ForbiddenError("订单不属于当前用户，无法查询")


def get_order(order_id: str, identity) -> dict:
    row = _get_order_row(order_id)
    if row is None:
        raise NotFoundError(f"订单 {order_id} 不存在")
    order = dict(row)
    _check_ownership(order, identity)
    with get_conn() as conn:
        items = [
            dict(item)
            for item in conn.execute(
                "SELECT product_id, title, price, qty FROM order_items WHERE order_id = ?",
                (order_id,),
            ).fetchall()
        ]
    order["items"] = items
    order["status_label"] = STATUS_LABELS.get(order["status"], order["status"])
    order["advice"] = STATUS_ADVICE.get(order["status"], "")
    return order


def order_card(order: dict) -> dict:
    """给前端/模型看的脱敏订单摘要。"""
    return {
        "order_id": order["id"],
        "status": order["status"],
        "status_label": order["status_label"],
        "amount": float(order["amount"]),
        "discount": float(order["discount"]),
        "created_at": order["created_at"],
        "paid_at": order.get("paid_at"),
        "shipped_at": order.get("shipped_at"),
        "signed_at": order.get("signed_at"),
        "receiver": mask_name(order.get("receiver_name", "")),
        "phone": mask_phone(order.get("receiver_phone", "")),
        "address": mask_address(order.get("address", "")),
        "items": [
            {
                "product_id": item["product_id"],
                "title": item["title"],
                "price": float(item["price"]),
                "qty": item["qty"],
            }
            for item in order.get("items", [])
        ],
        "advice": order.get("advice", ""),
    }


def order_text(order: dict) -> str:
    card = order_card(order)
    items = "；".join(
        f"{i['title']} × {i['qty']}（¥{i['price']:.0f}）" for i in card["items"]
    )
    return (
        f"订单 {card['order_id']}｜状态：{card['status_label']}｜实付 ¥{card['amount']:.0f}\n"
        f"商品：{items}\n收货人：{card['receiver']} {card['phone']}｜{card['address']}\n"
        f"下单：{card['created_at']}｜签收：{card['signed_at'] or '未签收'}\n"
        f"提示：{card['advice']}"
    )


def get_logistics(order_id: str, identity) -> dict:
    order = get_order(order_id, identity)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT time, status, description FROM logistics WHERE order_id = ? ORDER BY seq ASC",
            (order_id,),
        ).fetchall()
    events = [dict(row) for row in rows]
    latest = events[-1] if events else None
    stalled_hours = 0.0
    if latest and latest["status"] not in {"已签收", "派送中"}:
        try:
            last_time = datetime.strptime(latest["time"], "%Y-%m-%d %H:%M:%S")
            stalled_hours = (datetime.now() - last_time).total_seconds() / 3600
        except ValueError:
            stalled_hours = 0.0
    return {
        "order_id": order_id,
        "company": order.get("logistics_company") or "",
        "tracking_no": order.get("tracking_no") or "",
        "events": list(reversed(events)),
        "latest": latest,
        "stalled_hours": round(stalled_hours, 1),
        "is_stalled": stalled_hours >= 48,
    }


def logistics_text(data: dict) -> str:
    if not data["events"]:
        return f"订单 {data['order_id']} 暂无物流记录（可能尚未发货）。"
    lines = [
        f"订单 {data['order_id']}｜{data['company']}｜运单号 {data['tracking_no']}",
        f"最新状态：{data['latest']['status']} - {data['latest']['description']}",
    ]
    if data["is_stalled"]:
        lines.append(
            f"注意：物流已停滞约 {data['stalled_hours']:.0f} 小时（超过 48 小时），"
            "建议联系承运商核实或申请物流异常处理。"
        )
    lines.append("轨迹：")
    lines.extend(f"- {e['time']} {e['status']}：{e['description']}" for e in data["events"])
    return "\n".join(lines)
