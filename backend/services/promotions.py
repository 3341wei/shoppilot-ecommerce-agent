# -*- coding: utf-8 -*-
"""优惠券与到手价试算。"""
from __future__ import annotations

from datetime import date

from backend.services import catalog, rules
from backend.services.db import get_conn


def get_user_coupons(user_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.*, uc.used
               FROM user_coupons uc
               JOIN coupons c ON c.id = uc.coupon_id
               WHERE uc.user_id = ?
               ORDER BY c.end_at ASC""",
            (user_id,),
        ).fetchall()
    coupons = []
    for row in rows:
        coupon = dict(row)
        coupon["threshold"] = float(coupon["threshold"])
        coupon["discount"] = float(coupon["discount"])
        coupon["max_discount"] = (
            float(coupon["max_discount"]) if coupon["max_discount"] is not None else None
        )
        coupon["stackable"] = bool(coupon["stackable"])
        coupon["used"] = bool(coupon["used"])
        coupons.append(coupon)
    return coupons


def calculate_price(product_id: str, qty: int, user_id: str, today: date | None = None) -> dict:
    product = catalog.get_product(product_id)
    coupons = get_user_coupons(user_id)
    result = rules.best_price(
        product["price"], qty, coupons, product["category"], today=today
    )
    return {"product": product, "qty": max(1, int(qty)), **result}


def price_text(data: dict) -> str:
    product = data["product"]
    lines = [
        f"{product['title']} × {data['qty']}｜小计 ¥{data['subtotal']:.2f}",
    ]
    if data["applied"]:
        for item in data["applied"]:
            lines.append(f"- {item['name']}：−¥{item['amount']:.2f}")
        lines.append(f"到手价：¥{data['best_price']:.2f}（已省 ¥{data['total_discount']:.2f}）")
    else:
        lines.append("当前没有可用优惠券，到手价即小计金额。")
    if data["unavailable"]:
        top = data["unavailable"][:3]
        lines.append("暂不可用：" + "；".join(f"{c['name']}（{c['reason']}）" for c in top))
    return "\n".join(lines)


def to_card(data: dict) -> dict:
    product = data["product"]
    return {
        "product_id": product["id"],
        "title": product["title"],
        "qty": data["qty"],
        "subtotal": data["subtotal"],
        "best_price": data["best_price"],
        "total_discount": data["total_discount"],
        "applied": data["applied"],
        "unavailable": data["unavailable"],
    }
