# -*- coding: utf-8 -*-
"""业务服务集成测试：脱敏、越权、优惠试算、BM25 检索。"""
from __future__ import annotations

from datetime import date

import pytest

from backend.core.errors import ForbiddenError
from backend.services import analytics, knowledge, orders, promotions
from backend.services.identity import Identity

BUYER_1 = Identity(user_id="u_buyer_001", role="buyer", session_id="s_1")
BUYER_2 = Identity(user_id="u_buyer_002", role="buyer", session_id="s_1")
OPERATOR = Identity(user_id="u_ops_001", role="operator", session_id="s_1")


def test_order_card_masks_pii():
    order = orders.get_order("SO20261001001", BUYER_1)
    card = orders.order_card(order)
    assert card["receiver"] == "张*"
    assert card["phone"] == "138****8000"
    assert "世纪大道100号" not in card["address"]
    assert "1201" not in card["address"]


def test_buyer_cannot_read_others_order():
    with pytest.raises(ForbiddenError):
        orders.get_order("SO20261001006", BUYER_1)
    # 订单 006 属于 buyer2
    assert orders.get_order("SO20261001006", BUYER_2)["id"] == "SO20261001006"


def test_operator_can_read_any_order():
    assert orders.get_order("SO20261001006", OPERATOR)["id"] == "SO20261001006"


def test_logistics_detects_stall():
    data = orders.get_logistics("SO20261001003", BUYER_1)
    assert data["is_stalled"] is True
    assert data["stalled_hours"] > 48
    assert data["events"][0]["status"] == data["latest"]["status"]


def test_best_price_integration():
    # 种子优惠券已按今天平移，用真实今天的日期验证
    result = promotions.calculate_price("P2001", 1, BUYER_1.user_id, today=date.today())
    # C001 满 300 减 40 + C002 新人 20 元，叠加优于 C004 九折
    assert result["total_discount"] == 60.0
    assert result["best_price"] == 339.0
    assert {item["id"] for item in result["applied"]} == {"C001", "C002"}


def test_analytics_overview_matches_seed_and_shares_sum_to_100():
    data = analytics.sales_overview()
    assert data["paid_orders"] == 7
    assert data["gmv"] == 2483.0
    assert data["refund_rate"] == 14.29
    shares = [item["share"] for item in data["categories"]]
    assert all(0 < share <= 100 for share in shares)
    assert abs(sum(shares) - 100) <= 0.2


def test_inventory_alerts_include_seeded_shortages():
    data = analytics.inventory_alerts()
    ids = {item["product_id"] for item in data["alerts"]}
    assert {"P1003", "P2006", "P1006", "P1004", "P3003"} <= ids
    assert data["alert_count"] == len(data["alerts"])


def test_bm25_product_search_without_embedding_key():
    results = knowledge.search_products(
        "轻量缓震跑步鞋", category="运动户外", max_price=500, top_k=3
    )
    assert results
    assert results[0]["product"]["id"] == "P2001"


def test_policy_search_returns_cited_chunks():
    chunks = knowledge.search_policies("七天无理由退货", top_k=3)
    assert chunks
    assert all(chunk["source"] and chunk["text"] for chunk in chunks)
    assert any("退换货" in chunk["source"] for chunk in chunks)
