# -*- coding: utf-8 -*-
"""初始化演示数据库。

    python scripts/seed_db.py

可重复执行：每次会重建表并重新灌入固定数据，保证任何机器上的演示剧本一致。
不要在生产环境运行（会清空业务数据）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.config import ROOT_DIR as APP_ROOT  # noqa: E402
from backend.core.config import get_settings, reset_settings  # noqa: E402
from backend.services.db import SCHEMA  # noqa: E402

SEED_DIR = APP_ROOT / "data" / "seed"

# 种子数据以 2026-10-29 为基准日；灌库时整体平移到今天，
# 保证「最近 30 天」「签收 3 天/19 天」「物流停滞 3 天」等演示剧本不会随时间失效。
SEED_ANCHOR = date(2026, 10, 29)


def _shift_time(value: str | None, offset: timedelta) -> str | None:
    if not value:
        return value
    return (
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S") + offset
    ).strftime("%Y-%m-%d %H:%M:%S")


def _shift_day(value: str | None, offset: timedelta) -> str | None:
    if not value:
        return value
    return (datetime.strptime(value, "%Y-%m-%d").date() + offset).isoformat()

TABLES = [
    "audit_logs",
    "tickets",
    "user_coupons",
    "coupons",
    "logistics",
    "order_items",
    "orders",
    "products",
    "users",
]


def load(name: str):
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="重建 ShopPilot 演示数据库")
    parser.add_argument("--db", default="", help="自定义数据库路径（默认读取 DB_PATH）")
    args = parser.parse_args()

    if args.db:
        import os

        os.environ["DB_PATH"] = args.db
        reset_settings()

    settings = get_settings()
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    import sqlite3

    offset = date.today() - SEED_ANCHOR
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA)
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")

        conn.executemany(
            "INSERT INTO users (id, name, role, phone, address) VALUES (?, ?, ?, ?, ?)",
            [
                (u["id"], u["name"], u["role"], u.get("phone", ""), u.get("address", ""))
                for u in load("users.json")
            ],
        )
        conn.executemany(
            """INSERT INTO products
               (id, title, category, brand, price, original_price, stock, sales_7d,
                rating, sales_total, tags, attributes, description, sku_summary, image, special)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    p["id"], p["title"], p["category"], p.get("brand", ""),
                    p["price"], p["original_price"], p["stock"], p.get("sales_7d", 0),
                    p.get("rating", 0), p.get("sales_total", 0),
                    json.dumps(p.get("tags", []), ensure_ascii=False),
                    json.dumps(p.get("attributes", {}), ensure_ascii=False),
                    p.get("description", ""), p.get("sku_summary", ""),
                    p.get("image", ""), 1 if p.get("special") else 0,
                )
                for p in load("products.json")
            ],
        )
        conn.executemany(
            """INSERT INTO orders
               (id, user_id, status, discount, amount, receiver_name, receiver_phone, address,
                created_at, paid_at, shipped_at, signed_at, logistics_company, tracking_no)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    o["id"], o["user_id"], o["status"], o.get("discount", 0), o["amount"],
                    o.get("receiver_name", ""), o.get("receiver_phone", ""), o.get("address", ""),
                    _shift_time(o["created_at"], offset),
                    _shift_time(o.get("paid_at"), offset),
                    _shift_time(o.get("shipped_at"), offset),
                    _shift_time(o.get("signed_at"), offset),
                    o.get("logistics_company"), o.get("tracking_no"),
                )
                for o in load("orders.json")
            ],
        )
        conn.executemany(
            "INSERT INTO order_items (order_id, product_id, title, price, qty) VALUES (?, ?, ?, ?, ?)",
            [
                (i["order_id"], i["product_id"], i["title"], i["price"], i.get("qty", 1))
                for i in load("order_items.json")
            ],
        )
        logistics_rows = []
        for item in load("logistics.json"):
            # 种子 JSON 按“最新在前”编写；入库时反转为时间正序，
            # 服务层用 seq ASC 读出后，最后一条才是最新状态。
            for seq, event in enumerate(reversed(item["events"])):
                logistics_rows.append(
                    (
                        item["order_id"], seq, _shift_time(event["time"], offset),
                        event["status"], event["description"],
                    )
                )
        conn.executemany(
            "INSERT INTO logistics (order_id, seq, time, status, description) VALUES (?, ?, ?, ?, ?)",
            logistics_rows,
        )
        conn.executemany(
            """INSERT INTO coupons
               (id, name, kind, type, threshold, discount, max_discount, scope_category,
                start_at, end_at, stackable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    c["id"], c["name"], c["kind"], c["type"], c["threshold"], c["discount"],
                    c.get("max_discount"), c.get("scope_category"),
                    _shift_day(c["start_at"], offset), _shift_day(c["end_at"], offset),
                    1 if c.get("stackable", True) else 0,
                )
                for c in load("coupons.json")
            ],
        )
        conn.executemany(
            "INSERT INTO user_coupons (user_id, coupon_id, used) VALUES (?, ?, ?)",
            [(uc["user_id"], uc["coupon_id"], uc.get("used", 0)) for uc in load("user_coupons.json")],
        )
        conn.commit()

        counts = {
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "coupons": conn.execute("SELECT COUNT(*) FROM coupons").fetchone()[0],
        }
    finally:
        conn.close()

    print(f"数据库已重建: {db_path}")
    print(f"演示时间：{SEED_ANCHOR} → {date.today()}（整体平移 {offset.days} 天）")
    for key, value in counts.items():
        print(f"  {key:<10} {value}")
    print("下一步：python -m backend.services.ingest   # 可选，建立向量索引")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
