# -*- coding: utf-8 -*-
"""售后服务：资格判定、工单创建（确认制）、转人工。"""
from __future__ import annotations

import secrets
from datetime import date, datetime

from backend.core.context import get_request_id
from backend.core.errors import BadRequestError
from backend.services import actions, catalog, orders, rules
from backend.services.db import transaction
from backend.services.identity import Identity

TICKET_TYPES = {
    "return": "退货",
    "exchange": "换货",
    "repair": "维修",
    "complaint": "投诉",
}


def evaluate(
    order_id: str,
    identity: Identity,
    reason: str,
    opened: bool = False,
    today: date | None = None,
) -> dict:
    order = orders.get_order(order_id, identity)
    if not order["items"]:
        raise BadRequestError("订单没有商品明细，无法判定售后")
    product = catalog.get_product(order["items"][0]["product_id"])
    result = rules.check_return_eligibility(
        order, product, reason=reason, opened=opened, today=today
    )
    result["order"] = orders.order_card(order)
    return result


def _existing_pending_ticket(order_id: str, ticket_type: str) -> str | None:
    from backend.services.db import get_conn

    with get_conn() as conn:
        row = conn.execute(
            """SELECT id FROM tickets
               WHERE order_id = ? AND type = ? AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            (order_id, ticket_type),
        ).fetchone()
    return row["id"] if row else None


def request_ticket(
    identity: Identity,
    order_id: str,
    ticket_type: str,
    reason: str,
    opened: bool = False,
) -> dict:
    """校验业务前提并签发确认单；此时不写 tickets 表。"""
    if ticket_type not in TICKET_TYPES:
        raise BadRequestError("工单类型仅支持：" + "、".join(TICKET_TYPES))

    evaluation = evaluate(order_id, identity, reason, opened=opened)
    days = evaluation.get("days_since_signed")

    if ticket_type in {"return", "exchange"} and not evaluation["eligible"]:
        return {
            "ok": False,
            "message": "当前不满足退换条件，未创建工单。",
            "eligibility": evaluation,
        }
    if ticket_type == "repair" and evaluation["type"] not in {"质量问题退换", "保修维修"}:
        return {
            "ok": False,
            "message": "当前不满足免费维修条件，如为人为损坏可转人工咨询付费维修。",
            "eligibility": evaluation,
        }

    existing = _existing_pending_ticket(order_id, ticket_type)
    if existing:
        return {
            "ok": False,
            "message": f"该订单已有处理中的{TICKET_TYPES[ticket_type]}工单（{existing}），无需重复提交。",
            "eligibility": evaluation,
            "ticket_id": existing,
        }

    summary = (
        f"为订单 {order_id} 创建{TICKET_TYPES[ticket_type]}工单"
        f"（{evaluation['product_title']}，签收 {days} 天）：{reason}"
    )
    pending = actions.issue(
        identity,
        "create_ticket",
        summary,
        {
            "order_id": order_id,
            "ticket_type": ticket_type,
            "reason": reason,
            "opened": opened,
        },
    )
    return {
        "ok": True,
        "message": "已生成确认单，用户确认后才会真正创建工单。",
        "pending_action": pending,
        "eligibility": evaluation,
    }


def _new_ticket_id() -> str:
    return "AS" + datetime.now().strftime("%Y%m%d%H%M%S") + secrets.token_hex(2).upper()


def execute_create_ticket(payload: dict, identity: Identity) -> dict:
    """确认后执行：写工单 + 审计，二者同事务。"""
    order_id = payload["order_id"]
    # 防御性复核：确认时再次校验归属，避免签发后数据被篡改
    orders.get_order(order_id, identity)

    ticket_id = _new_ticket_id()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction() as conn:
        conn.execute(
            """INSERT INTO tickets (id, order_id, user_id, type, reason, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (
                ticket_id,
                order_id,
                identity.user_id,
                payload["ticket_type"],
                payload.get("reason", ""),
                now,
            ),
        )
        conn.execute(
            """INSERT INTO audit_logs (request_id, user_id, action, target, result, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                get_request_id(),
                identity.user_id,
                "create_ticket",
                ticket_id,
                f"type={payload['ticket_type']};order={order_id}",
                now,
            ),
        )
    return {
        "status": "created",
        "ticket_id": ticket_id,
        "order_id": order_id,
        "ticket_type": payload["ticket_type"],
        "ticket_type_label": TICKET_TYPES[payload["ticket_type"]],
        "reason": payload.get("reason", ""),
        "state": "pending",
        "created_at": now,
        "message": f"工单 {ticket_id} 已创建，客服将在 24 小时内处理。",
    }


def ticket_text(result: dict) -> str:
    if not result.get("ok"):
        return result.get("message", "无法创建工单")
    pending = result["pending_action"]
    eligibility = result["eligibility"]
    return (
        f"已生成确认单：{pending['summary']}\n"
        f"判定依据：{eligibility['type']}｜签收 {eligibility['days_since_signed']} 天\n"
        "请用户在确认卡片中点击「确认创建」，工单才会真正生成。"
    )


def handoff(identity: Identity, reason: str) -> dict:
    handoff_id = "HO" + datetime.now().strftime("%Y%m%d%H%M%S") + secrets.token_hex(2).upper()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction() as conn:
        conn.execute(
            """INSERT INTO audit_logs (request_id, user_id, action, target, result, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (get_request_id(), identity.user_id, "handoff", handoff_id, reason[:200], now),
        )
    return {
        "handoff_id": handoff_id,
        "status": "queued",
        "message": f"已为您转接人工客服（{handoff_id}），请留意会话窗口通知。",
    }


# 注册确认单执行器
actions.register_executor("create_ticket", execute_create_ticket)
