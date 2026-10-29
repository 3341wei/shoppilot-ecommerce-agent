# -*- coding: utf-8 -*-
"""运营分析：销售指标、类目下钻、库存预警。

不做 Text-to-SQL：所有指标都是预定义查询，口径稳定、无注入风险。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from backend.core.errors import BadRequestError
from backend.services import rules
from backend.services.db import get_conn

_LEVEL_ORDER = {"out": 0, "critical": 1, "warning": 2, "slow": 3, "normal": 4}


def _parse_day(value: str | None, default: date) -> date:
    if not value:
        return default
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise BadRequestError("日期格式应为 YYYY-MM-DD")


def _period_metrics(start: date, end: date) -> dict:
    start_s, end_s = start.isoformat(), end.isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, status, amount FROM orders
               WHERE paid_at IS NOT NULL
                 AND substr(paid_at, 1, 10) BETWEEN ? AND ?""",
            (start_s, end_s),
        ).fetchall()
        category_rows = conn.execute(
            """SELECT p.category AS category,
                      SUM(oi.price * oi.qty) AS gmv,
                      COUNT(DISTINCT o.id) AS orders
               FROM order_items oi
               JOIN orders o ON o.id = oi.order_id
               JOIN products p ON p.id = oi.product_id
               WHERE o.paid_at IS NOT NULL
                 AND substr(o.paid_at, 1, 10) BETWEEN ? AND ?
               GROUP BY p.category
               ORDER BY gmv DESC""",
            (start_s, end_s),
        ).fetchall()

    paid_orders = len(rows)
    gmv = round(sum(float(row["amount"]) for row in rows), 2)
    refund_orders = sum(1 for row in rows if row["status"] == "refunding")
    # 类目金额按商品原价汇总（订单级优惠无法准确拆分到单品），
    # 因此占比分母用类目合计，避免与扣减后的 GMV 口径混用导致占比超过 100%。
    category_total = sum(float(row["gmv"]) for row in category_rows)
    categories = [
        {
            "category": row["category"],
            "gmv": round(float(row["gmv"]), 2),
            "orders": int(row["orders"]),
            "share": round(float(row["gmv"]) / category_total * 100, 1)
            if category_total
            else 0.0,
        }
        for row in category_rows
    ]
    return {
        "start": start_s,
        "end": end_s,
        "gmv": gmv,
        "paid_orders": paid_orders,
        "aov": round(gmv / paid_orders, 2) if paid_orders else 0.0,
        "refund_orders": refund_orders,
        "refund_rate": round(refund_orders / paid_orders * 100, 2) if paid_orders else 0.0,
        "categories": categories,
    }


def sales_overview(start_date: str | None = None, end_date: str | None = None) -> dict:
    today = date.today()
    end = _parse_day(end_date, today)
    start = _parse_day(start_date, end - timedelta(days=29))
    if start > end:
        raise BadRequestError("开始日期不能晚于结束日期")

    current = _period_metrics(start, end)
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    previous = _period_metrics(prev_start, prev_end)

    def delta(key: str) -> float:
        before = float(previous[key])
        if before == 0:
            return 0.0
        return round((float(current[key]) - before) / before * 100, 2)

    current["previous"] = previous
    current["changes"] = {
        "gmv_pct": delta("gmv"),
        "orders_pct": delta("paid_orders"),
        "aov_pct": delta("aov"),
        "refund_rate_pp": round(
            float(current["refund_rate"]) - float(previous["refund_rate"]), 2
        ),
    }
    current["note"] = (
        "口径：GMV 为统计期内已付款订单实付金额之和；"
        "退款率 = 退款中订单数 / 已付款订单数；客单价 = GMV / 已付款订单数；"
        "类目金额按商品原价汇总（未扣订单级优惠），占比以类目合计为分母。"
    )
    return current


def metrics_text(data: dict) -> str:
    changes = data["changes"]
    sign = lambda v: f"{v:+.1f}%" if v else "持平"  # noqa: E731
    lines = [
        f"统计期：{data['start']} ~ {data['end']}（对比上一个等长周期）",
        f"GMV：¥{data['gmv']:.2f}（{sign(changes['gmv_pct'])}）",
        f"已付款订单：{data['paid_orders']} 单（{sign(changes['orders_pct'])}）",
        f"客单价：¥{data['aov']:.2f}（{sign(changes['aov_pct'])}）",
        f"退款率：{data['refund_rate']:.2f}%（环比 {changes['refund_rate_pp']:+.2f} 个百分点）",
    ]
    if data["categories"]:
        lines.append("类目商品金额（未扣优惠）：")
        lines.extend(
            f"- {c['category']}：¥{c['gmv']:.2f}，占比 {c['share']:.1f}%，{c['orders']} 单"
            for c in data["categories"]
        )
    lines.append(data["note"])
    return "\n".join(lines)


def inventory_alerts() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()

    items = []
    for row in rows:
        product = dict(row)
        status = rules.inventory_status(product["stock"], product["sales_7d"])
        product["inventory"] = status
        items.append(product)

    alerts = [item for item in items if item["inventory"]["level"] != "normal"]
    alerts.sort(key=lambda item: (_LEVEL_ORDER[item["inventory"]["level"]], item["stock"]))
    return {
        "total_products": len(items),
        "alert_count": len(alerts),
        "alerts": [
            {
                "product_id": item["id"],
                "title": item["title"],
                "category": item["category"],
                "stock": item["stock"],
                "sales_7d": item["sales_7d"],
                "level": item["inventory"]["level"],
                "label": item["inventory"]["label"],
                "safety_stock": item["inventory"]["safety_stock"],
                "suggested_replenish": item["inventory"]["suggested_replenish"],
            }
            for item in alerts
        ],
        "note": "安全库存 = 近 7 日销量 × 1.2；补货建议按覆盖两周销量估算。",
    }


def inventory_text(data: dict) -> str:
    if not data["alerts"]:
        return "当前没有库存预警，全部商品库存正常。"
    lines = [f"共 {data['alert_count']} 个商品需要关注（总计 {data['total_products']} 个）："]
    lines.extend(
        f"- [{a['label']}] {a['product_id']} {a['title']}：库存 {a['stock']}，"
        f"近 7 日销量 {a['sales_7d']}，安全库存 {a['safety_stock']}，建议补货 {a['suggested_replenish']}"
        for a in data["alerts"]
    )
    lines.append(data["note"])
    return "\n".join(lines)
