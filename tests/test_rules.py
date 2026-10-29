# -*- coding: utf-8 -*-
"""规则引擎纯函数测试：价格、售后资格、库存预警。"""
from __future__ import annotations

from datetime import date

from backend.services import rules

TODAY = date(2026, 10, 29)


def coupon(
    *,
    cid="C1",
    name="测试券",
    kind="shop",
    ctype="fixed",
    threshold=0,
    discount=10,
    max_discount=None,
    scope=None,
    start="2026-10-01",
    end="2026-11-30",
    stackable=True,
    used=False,
):
    return {
        "id": cid,
        "name": name,
        "kind": kind,
        "type": ctype,
        "threshold": threshold,
        "discount": discount,
        "max_discount": max_discount,
        "scope_category": scope,
        "start_at": start,
        "end_at": end,
        "stackable": stackable,
        "used": used,
    }


def test_coupon_amount_rejects_expired_and_below_threshold():
    expired = coupon(end="2026-10-01")
    assert rules.coupon_amount(expired, 100, "数码", TODAY) == (False, 0.0, "已过期")

    below = coupon(threshold=300, discount=40)
    ok, amount, reason = rules.coupon_amount(below, 299, "数码", TODAY)
    assert not ok and amount == 0
    assert "未满足满 300" in reason


def test_coupon_amount_category_scope():
    category_coupon = coupon(scope="数码", threshold=200, discount=30)
    assert rules.coupon_amount(category_coupon, 499, "数码", TODAY)[:2] == (True, 30.0)
    ok, _, reason = rules.coupon_amount(category_coupon, 499, "家居", TODAY)
    assert not ok and "仅限数码" in reason


def test_coupon_amount_percent_respects_cap():
    percent = coupon(ctype="percent", discount=10, max_discount=50)
    ok, amount, _ = rules.coupon_amount(percent, 1000, "数码", TODAY)
    assert ok and amount == 50.0


def test_best_price_prefers_stackable_combination():
    coupons = [
        coupon(cid="A", kind="shop", threshold=300, discount=40),
        coupon(cid="B", kind="platform", threshold=0, discount=20),
        coupon(cid="C", kind="category", scope="数码", threshold=200, discount=30),
        # 不可叠加：单独使用最多减 49.9，低于三张叠加的 90
        coupon(cid="D", kind="platform", ctype="percent", discount=10, max_discount=50, stackable=False),
    ]
    result = rules.best_price(499, 1, coupons, "数码", TODAY)
    assert result["subtotal"] == 499.0
    assert result["total_discount"] == 90.0
    assert result["best_price"] == 409.0
    assert {item["id"] for item in result["applied"]} == {"A", "B", "C"}


def test_best_price_uses_non_stackable_when_better():
    coupons = [
        coupon(cid="A", kind="shop", threshold=300, discount=20),
        coupon(cid="D", kind="platform", ctype="percent", discount=10, max_discount=50, stackable=False),
    ]
    result = rules.best_price(499, 1, coupons, "数码", TODAY)
    assert result["total_discount"] == 49.9
    assert result["best_price"] == 449.1


def _order(status="signed", signed_at="2026-10-20 16:05:00"):
    return {"id": "SO1", "status": status, "signed_at": signed_at}


def _product(special=False):
    return {"id": "P1", "title": "测试商品", "special": special}


def test_return_within_seven_days():
    result = rules.check_return_eligibility(
        _order(signed_at="2026-10-26 11:30:00"),
        _product(),
        reason="尺码不合适",
        opened=False,
        today=TODAY,
    )
    assert result["eligible"] is True
    assert result["type"] == "七天无理由退货"
    assert result["days_since_signed"] == 3


def test_return_rejected_after_seven_days_but_repair_available():
    result = rules.check_return_eligibility(
        _order(), _product(), reason="不想要了", opened=False, today=TODAY
    )
    assert result["eligible"] is False
    assert result["type"] == "超过七天无理由期限"
    assert any("保修" in alt for alt in result["alternatives"])


def test_quality_issue_within_fifteen_days():
    result = rules.check_return_eligibility(
        _order(), _product(), reason="耳机有异响，无法使用", opened=True, today=TODAY
    )
    assert result["eligible"] is True
    assert result["type"] == "质量问题退换"


def test_special_product_opened_cannot_return_without_reason():
    result = rules.check_return_eligibility(
        _order(), _product(special=True), reason="不喜欢", opened=True, today=TODAY
    )
    assert result["eligible"] is False
    assert result["type"] == "不支持无理由退货"


def test_unsigned_order_cannot_apply():
    result = rules.check_return_eligibility(
        _order(status="shipped", signed_at=None),
        _product(),
        reason="不想要了",
        today=TODAY,
    )
    assert result["eligible"] is False
    assert result["type"] == "不可申请"


def test_inventory_levels():
    assert rules.inventory_status(0, 10)["level"] == "out"
    assert rules.inventory_status(5, 100)["level"] == "critical"
    assert rules.inventory_status(100, 100)["level"] == "warning"
    assert rules.inventory_status(300, 100)["level"] == "normal"
    assert rules.inventory_status(150, 0)["level"] == "slow"
    assert rules.inventory_status(5, 100)["suggested_replenish"] > 0
