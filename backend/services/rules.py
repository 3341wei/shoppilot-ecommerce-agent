# -*- coding: utf-8 -*-
"""业务规则引擎（纯函数，无 IO，可表驱动测试）。

为什么不用 LLM 算：
- 价格、退款资格、库存预警都有明确的业务口径，必须可复现；
- LLM 只负责理解意图和转述结论，不负责“算钱”和“判资格”。
"""
from __future__ import annotations

import math
from datetime import date, datetime
from itertools import product

QUALITY_KEYWORDS = (
    "质量", "坏", "故障", "坏掉", "破损", "碎裂", "缺陷", "没声音", "无声",
    "不能", "无法", "失灵", "开不了", "充不进", "断连", "异响", "漏液",
)

_POLICY_REF_RETURN = "退换货政策.md#一、七天无理由退货"
_POLICY_REF_QUALITY = "退换货政策.md#二、质量问题退换"
_POLICY_REF_OPENED = "退换货政策.md#三、已拆封商品的判定"
_POLICY_REF_SPECIAL = "特殊商品说明.md#一、数码类"


def round_money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def coupon_amount(
    coupon: dict, subtotal: float, category: str, today: date | None = None
) -> tuple[bool, float, str]:
    """计算单张券的减免金额，返回 (可用, 金额, 不可用原因)。"""
    today = today or date.today()
    today_str = today.isoformat()

    if coupon.get("used"):
        return False, 0.0, "已使用"
    if str(coupon.get("start_at", "")) > today_str:
        return False, 0.0, "未到使用时间"
    if str(coupon.get("end_at", "")) < today_str:
        return False, 0.0, "已过期"
    if subtotal < float(coupon.get("threshold", 0)):
        return False, 0.0, f"未满足满 {coupon.get('threshold', 0):.0f} 元门槛"

    scope = coupon.get("scope_category")
    if scope and scope != category:
        return False, 0.0, f"仅限{scope}类目使用"

    if coupon["type"] == "fixed":
        amount = min(float(coupon["discount"]), subtotal)
    else:
        amount = subtotal * float(coupon["discount"]) / 100.0
        max_discount = coupon.get("max_discount")
        if max_discount is not None:
            amount = min(amount, float(max_discount))
    amount = round_money(amount)
    if amount <= 0:
        return False, 0.0, "优惠金额为 0"
    return True, amount, ""


def best_price(
    price: float,
    qty: int,
    coupons: list[dict],
    category: str,
    today: date | None = None,
) -> dict:
    """枚举优惠组合，返回实付最低的方案。"""
    qty = max(1, int(qty))
    subtotal = round_money(float(price) * qty)
    today = today or date.today()

    valid: list[tuple[dict, float]] = []
    unavailable: list[dict] = []
    for coupon in coupons:
        ok, amount, reason = coupon_amount(coupon, subtotal, category, today)
        if ok:
            valid.append((coupon, amount))
        else:
            unavailable.append({"id": coupon["id"], "name": coupon["name"], "reason": reason})

    stackable = [(c, a) for c, a in valid if c.get("stackable")]
    fixed_only = [(c, a) for c, a in valid if not c.get("stackable")]

    candidates: list[list[tuple[dict, float]]] = [[]]
    # 不可叠加券只能单独使用
    candidates.extend([[item] for item in fixed_only])

    # 可叠加券：每种 kind 最多选一张
    groups: dict[str, list[tuple[dict, float]]] = {}
    for item in stackable:
        groups.setdefault(item[0]["kind"], []).append(item)
    if groups:
        options = [[None] + group for group in groups.values()]
        for combo in product(*options):
            chosen = [item for item in combo if item is not None]
            if chosen:
                candidates.append(chosen)

    best_combo: list[tuple[dict, float]] = []
    best_discount = 0.0
    for combo in candidates:
        discount = round_money(sum(amount for _, amount in combo))
        if discount > subtotal:
            continue
        if discount > best_discount or (
            discount == best_discount and 0 < len(combo) < len(best_combo)
        ):
            best_discount = discount
            best_combo = combo

    applied = [
        {"id": c["id"], "name": c["name"], "amount": round_money(a)}
        for c, a in sorted(best_combo, key=lambda item: item[1], reverse=True)
    ]
    return {
        "subtotal": subtotal,
        "total_discount": round_money(best_discount),
        "best_price": round_money(subtotal - best_discount),
        "applied": applied,
        "unavailable": unavailable,
        "valid_coupon_count": len(valid),
    }


def check_return_eligibility(
    order: dict,
    product: dict,
    reason: str,
    opened: bool = False,
    today: date | None = None,
) -> dict:
    """判定退换资格。返回结构化结论，供工具与前端直接使用。"""
    today = today or date.today()
    reason = (reason or "").strip()
    refs = [_POLICY_REF_RETURN]
    base = {
        "order_id": order.get("id"),
        "product_id": product.get("id"),
        "product_title": product.get("title"),
        "opened": bool(opened),
        "reason": reason,
        "days_since_signed": None,
        "policy_refs": refs,
        "alternatives": [],
    }

    status = order.get("status")
    if status == "refunding":
        return {**base, "eligible": False, "type": "处理中", "reasons": ["该订单已有退款申请正在处理"], "alternatives": ["等待审核结果", "联系人工客服"]}
    if status not in {"signed", "completed"}:
        return {
            **base,
            "eligible": False,
            "type": "不可申请",
            "reasons": ["订单尚未签收，需先完成签收后再申请售后"],
            "alternatives": ["拒收包裹", "联系人工客服"],
        }

    signed = _parse_date(order.get("signed_at"))
    if signed is None:
        return {**base, "eligible": False, "type": "不可申请", "reasons": ["缺少签收时间，无法判定"], "alternatives": ["联系人工客服"]}

    days = max(0, (today - signed).days)
    base["days_since_signed"] = days
    is_quality = any(word in reason for word in QUALITY_KEYWORDS)
    special = bool(product.get("special"))

    if is_quality:
        base["policy_refs"] = [_POLICY_REF_QUALITY]
        if days <= 15:
            return {
                **base,
                "eligible": True,
                "type": "质量问题退换",
                "reasons": [f"签收后 {days} 天，属于质量问题 15 日内，可退货、换货或维修", "质量问题运费由商家承担"],
                "alternatives": [],
            }
        if days <= 365:
            return {
                **base,
                "eligible": True,
                "type": "保修维修",
                "reasons": [f"签收后 {days} 天，已超过 15 日退换期，但仍在 12 个月保修期内，可申请维修"],
                "alternatives": ["申请维修工单", "联系人工客服"],
            }
        return {
            **base,
            "eligible": False,
            "type": "超出保修",
            "reasons": [f"签收后 {days} 天，已超过 12 个月保修期"],
            "alternatives": ["付费维修", "联系人工客服"],
        }

    # 非质量问题
    if special and opened:
        base["policy_refs"] = [_POLICY_REF_OPENED, _POLICY_REF_SPECIAL]
        alternatives = ["如存在质量问题，可申请质量检测", "联系人工客服协商"]
        if days <= 365:
            alternatives.insert(0, "申请保修维修")
        return {
            **base,
            "eligible": False,
            "type": "不支持无理由退货",
            "reasons": [
                f"签收后 {days} 天",
                "该商品属于拆封后不支持无理由退货的特殊品类",
                "已拆封使用，影响二次销售",
            ],
            "alternatives": alternatives,
        }

    if days <= 7:
        return {
            **base,
            "eligible": True,
            "type": "七天无理由退货",
            "reasons": [f"签收后 {days} 天，在 7 天无理由期内", "需保证商品、配件、包装完整，不影响二次销售"],
            "alternatives": [],
        }

    alternatives = ["如存在质量问题，可申请质量检测"]
    if days <= 365:
        alternatives.insert(0, "申请保修维修")
    alternatives.append("联系人工客服协商")
    return {
        **base,
        "eligible": False,
        "type": "超过七天无理由期限",
        "reasons": [f"签收后 {days} 天，已超过 7 天无理由退货期"],
        "alternatives": alternatives,
    }


def inventory_status(stock: int, sales_7d: int) -> dict:
    """按近 7 日销量推算安全库存，输出预警级别。"""
    stock = int(stock)
    sales_7d = int(sales_7d)
    safety_stock = int(math.ceil(sales_7d * 1.2))
    suggested = int(math.ceil(max(0, safety_stock * 2 - stock)))

    if stock == 0:
        level, label = "out", "断货"
    elif sales_7d == 0 and stock > 20:
        level, label = "slow", "滞销"
    elif stock < safety_stock * 0.5:
        level, label = "critical", "紧急"
    elif stock < safety_stock:
        level, label = "warning", "紧张"
    else:
        level, label = "normal", "正常"

    return {
        "stock": stock,
        "sales_7d": sales_7d,
        "safety_stock": safety_stock,
        "level": level,
        "label": label,
        "suggested_replenish": suggested if level in {"out", "critical", "warning"} else 0,
    }
