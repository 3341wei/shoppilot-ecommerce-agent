# -*- coding: utf-8 -*-
"""生成器：订单状态、时间与物流轨迹必须内在一致，且结果可复现。"""
from datetime import datetime

from scripts.generate_demo_data import _buyers, build_orders, load_seed

NOW = datetime(2026, 10, 29, 12, 0, 0)


def _generate(count: int = 80, seed: int = 42) -> list[dict]:
    return build_orders(
        load_seed("products.json"), _buyers(), count, now=NOW, seed=seed
    )


def test_generated_orders_are_internally_consistent():
    orders = _generate()

    assert len(orders) == 80
    assert len({order["id"] for order in orders}) == 80
    for order in orders:
        assert order["id"].startswith("SOG")
        assert order["items"]
        assert order["amount"] > 0
        assert order["created_at"] <= NOW.strftime("%Y-%m-%d %H:%M:%S")

        if order["status"] == "pending_payment":
            assert order["paid_at"] is None
            assert order["shipped_at"] is None
            assert order["signed_at"] is None
            assert order["logistics"] == []
        elif order["status"] == "shipped":
            assert order["paid_at"] and order["shipped_at"]
            assert order["signed_at"] is None
            assert order["logistics"]
        else:
            assert order["paid_at"] and order["shipped_at"] and order["signed_at"]
            assert order["created_at"] <= order["paid_at"] <= order["shipped_at"] <= order["signed_at"]
            times = [event[0] for event in order["logistics"]]
            assert times == sorted(times)
            assert order["logistics"][-1][1] == "已签收"


def test_generated_orders_are_reproducible():
    first = _generate(seed=42)
    second = _generate(seed=42)
    third = _generate(seed=43)

    assert first == second
    assert first != third
    # 不占用剧本订单号段
    assert all(not order["id"].startswith("SO2026") for order in first)
