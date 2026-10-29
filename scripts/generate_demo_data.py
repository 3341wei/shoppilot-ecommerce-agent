# -*- coding: utf-8 -*-
"""在基础演示数据之上生成 200+ 笔模拟订单，让报表和指标更接近真实规模。

    python scripts/seed_db.py
    python scripts/generate_demo_data.py --count 240

设计原则：
- 保留 seed_db 灌入的 8 笔剧本订单，不覆盖、不改动；
- 生成数据使用固定随机种子，可重复复现；
- 订单号统一以 SOG 开头，重跑时只清理上一次生成的订单；
- 商品、用户、价格全部复用 data/seed，不凭空编造新商品；
- 订单时间、状态、物流轨迹保持内在一致（未付款订单没有支付/物流）。
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.config import ROOT_DIR as APP_ROOT  # noqa: E402
from backend.core.config import get_settings, reset_settings  # noqa: E402

SEED_DIR = APP_ROOT / "data" / "seed"
ORDER_PREFIX = "SOG"
STATUS_WEIGHTS = [
    ("completed", 48),
    ("signed", 20),
    ("shipped", 10),
    ("refunding", 8),
    ("pending_payment", 14),
]

COMPANIES = [
    ("顺丰速运", "SF"),
    ("中通快递", "ZT"),
    ("圆通速递", "YT"),
    ("韵达快递", "YD"),
    ("京东物流", "JD"),
]

# 额外演示买家：真实项目里订单量上来后不可能只有两个用户
DEMO_USERS = [
    ("u_demo_001", "陈晨", "13600136001", "广州市天河区体育西路 103 号 1203 室"),
    ("u_demo_002", "刘洋", "13600136002", "深圳市南山区科技园科苑路 15 号 A 座 801"),
    ("u_demo_003", "赵敏", "13600136003", "成都市武侯区天府大道北段 1700 号 2 栋 602"),
    ("u_demo_004", "孙悦", "13600136004", "南京市鼓楼区中山北路 88 号 1508"),
    ("u_demo_005", "周杰", "13600136005", "武汉市洪山区珞喻路 726 号 3 栋 1102"),
    ("u_demo_006", "吴静", "13600136006", "西安市雁塔区科技路 48 号 1 单元 903"),
    ("u_demo_007", "郑凯", "13600136007", "苏州市工业园区星湖街 328 号 705"),
    ("u_demo_008", "王芳", "13600136008", "重庆市渝北区金开大道 1001 号 1806"),
    ("u_demo_009", "李明", "13600136009", "长沙市岳麓区麓谷大道 658 号 502"),
    ("u_demo_010", "张婷", "13600136010", "青岛市市南区香港中路 61 号 1201"),
]


def load_seed(name: str):
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def _fmt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _buyers() -> list[dict]:
    users = [u for u in load_seed("users.json") if u.get("role") == "buyer"]
    for user_id, name, phone, address in DEMO_USERS:
        users.append(
            {"id": user_id, "name": name, "role": "buyer", "phone": phone, "address": address}
        )
    return users


def _logistics_events(order: dict) -> list[tuple[str, str, str]]:
    """返回 (时间, 状态, 描述)，按时间从早到晚排列。"""
    if not order["paid_at"]:
        return []

    shipped = _parse_time(order["shipped_at"])
    signed = _parse_time(order["signed_at"])
    company = order["logistics_company"]

    events: list[tuple[str, str, str]] = [
        (_fmt(shipped), "已揽收", f"{company}已揽收"),
    ]
    if signed:
        events.extend(
            [
                (_fmt(shipped + timedelta(hours=10)), "运输中", "快件已到达转运中心"),
                (_fmt(signed - timedelta(hours=6)), "派送中", "快递员正在派送，请保持电话畅通"),
                (_fmt(signed), "已签收", "快件已由本人签收，感谢使用"),
            ]
        )
    else:
        events.append(
            (_fmt(shipped + timedelta(hours=12)), "运输中", "快件已到达转运中心，等待下一站中转")
        )
    return events


def _parse_time(value: str | None) -> datetime | None:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S") if value else None


def build_orders(
    products: list[dict],
    buyers: list[dict],
    count: int = 240,
    *,
    now: datetime | None = None,
    seed: int = 20261029,
) -> list[dict]:
    """生成订单（含明细与物流），不写库，便于测试。"""
    now = (now or datetime.now()).replace(microsecond=0)
    rng = random.Random(seed)
    statuses = [name for name, _ in STATUS_WEIGHTS]
    weights = [weight for _, weight in STATUS_WEIGHTS]
    date_tag = now.strftime("%Y%m%d")
    orders: list[dict] = []

    for index in range(1, count + 1):
        status = rng.choices(statuses, weights=weights, k=1)[0]
        user = rng.choice(buyers)
        company, company_code = rng.choice(COMPANIES)

        chosen = rng.sample(products, k=1 if rng.random() < 0.78 else 2)
        items = []
        subtotal = 0.0
        for product in chosen:
            qty = 1 if rng.random() < 0.86 else 2
            subtotal += float(product["price"]) * qty
            items.append(
                {
                    "product_id": product["id"],
                    "title": product["title"],
                    "price": float(product["price"]),
                    "qty": qty,
                }
            )

        discount = min(rng.choice([0, 0, 0, 10, 20, 30, 40, 50]), subtotal - 1)
        amount = round(subtotal - discount, 2)

        if status == "pending_payment":
            created = now - timedelta(
                days=rng.randint(0, 10), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
            )
            paid = shipped = signed = None
        elif status == "shipped":
            shipped_at = now - timedelta(
                days=rng.randint(2, 6), hours=rng.randint(0, 12), minutes=rng.randint(0, 59)
            )
            paid = shipped_at - timedelta(hours=rng.randint(4, 20))
            created = paid - timedelta(minutes=rng.randint(5, 90))
            shipped = shipped_at
            signed = None
        else:
            signed_at = now - timedelta(
                days=rng.randint(8, 58), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
            )
            shipped_at = signed_at - timedelta(days=rng.randint(2, 4), hours=rng.randint(0, 8))
            paid = shipped_at - timedelta(hours=rng.randint(6, 30))
            created = paid - timedelta(minutes=rng.randint(5, 90))
            shipped = shipped_at
            signed = signed_at

        order = {
            "id": f"{ORDER_PREFIX}{date_tag}{index:04d}",
            "user_id": user["id"],
            "status": status,
            "discount": discount,
            "amount": amount,
            "receiver_name": user["name"],
            "receiver_phone": user["phone"],
            "address": user["address"],
            "created_at": _fmt(created),
            "paid_at": _fmt(paid) if paid else None,
            "shipped_at": _fmt(shipped) if shipped else None,
            "signed_at": _fmt(signed) if signed else None,
            "logistics_company": company if shipped else None,
            "tracking_no": f"{company_code}{rng.randint(10**11, 10**12 - 1)}" if shipped else None,
            "items": items,
        }
        order["logistics"] = _logistics_events(order)
        orders.append(order)

    return orders


def _ensure_base_data(db_path: Path, db_arg: str) -> None:
    """数据库为空时先跑基础 seed，避免生成器依赖手工步骤。"""
    if not db_path.exists():
        needs_seed = True
    else:
        conn = sqlite3.connect(str(db_path))
        try:
            needs_seed = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        except sqlite3.OperationalError:
            needs_seed = True
        finally:
            conn.close()

    if not needs_seed:
        return

    print("数据库为空，先执行基础 seed ...")
    command = [sys.executable, str(ROOT_DIR / "scripts" / "seed_db.py")]
    if db_arg:
        command.extend(["--db", db_arg])
    subprocess.run(command, check=True)


def _clear_generated(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        f"SELECT id FROM orders WHERE id LIKE '{ORDER_PREFIX}%'"
    ).fetchall()
    ids = [row[0] for row in rows]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    # 先清理依赖行，避免外键约束阻止删除
    conn.execute(f"DELETE FROM tickets WHERE order_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM order_items WHERE order_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM logistics WHERE order_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM orders WHERE id IN ({placeholders})", ids)


def insert_orders(conn: sqlite3.Connection, orders: list[dict]) -> None:
    for user_id, name, phone, address in DEMO_USERS:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, name, role, phone, address) VALUES (?, ?, 'buyer', ?, ?)",
            (user_id, name, phone, address),
        )

    for order in orders:
        conn.execute(
            """INSERT INTO orders
               (id, user_id, status, discount, amount, receiver_name, receiver_phone, address,
                created_at, paid_at, shipped_at, signed_at, logistics_company, tracking_no)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order["id"], order["user_id"], order["status"], order["discount"],
                order["amount"], order["receiver_name"], order["receiver_phone"],
                order["address"], order["created_at"], order["paid_at"],
                order["shipped_at"], order["signed_at"], order["logistics_company"],
                order["tracking_no"],
            ),
        )
        for item in order["items"]:
            conn.execute(
                "INSERT INTO order_items (order_id, product_id, title, price, qty) VALUES (?, ?, ?, ?, ?)",
                (order["id"], item["product_id"], item["title"], item["price"], item["qty"]),
            )
        for seq, (event_time, status, description) in enumerate(order["logistics"]):
            conn.execute(
                "INSERT INTO logistics (order_id, seq, time, status, description) VALUES (?, ?, ?, ?, ?)",
                (order["id"], seq, event_time, status, description),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 200+ 笔模拟订单，保留 8 笔剧本订单")
    parser.add_argument("--count", type=int, default=240, help="生成订单数，默认 240")
    parser.add_argument("--db", default="", help="自定义数据库路径（默认读取 DB_PATH）")
    parser.add_argument("--seed", type=int, default=20261029, help="随机种子，默认固定以保证可复现")
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count 必须大于 0")

    if args.db:
        import os

        os.environ["DB_PATH"] = args.db
        reset_settings()

    settings = get_settings()
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_base_data(db_path, args.db)

    products = load_seed("products.json")
    orders = build_orders(products, _buyers(), args.count, seed=args.seed)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        _clear_generated(conn)
        insert_orders(conn, orders)
        conn.commit()

        total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        paid_orders = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE paid_at IS NOT NULL"
        ).fetchone()[0]
        min_day, max_day = conn.execute(
            "SELECT MIN(substr(paid_at, 1, 10)), MAX(substr(paid_at, 1, 10)) "
            "FROM orders WHERE paid_at IS NOT NULL"
        ).fetchone()
        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY COUNT(*) DESC"
        ).fetchall()
    finally:
        conn.close()

    print(f"已生成 {len(orders)} 笔模拟订单（保留 8 笔剧本订单）")
    print(f"数据库：{db_path}")
    print(f"订单总数：{total_orders}｜已付款：{paid_orders}｜支付日期：{min_day} ~ {max_day}")
    print("状态分布：" + "，".join(f"{status} {count}" for status, count in status_rows))
    print("提示：运营指标会随数据量变化；如需恢复固定剧本，重新执行 python scripts/seed_db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
