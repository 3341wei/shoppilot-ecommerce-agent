# -*- coding: utf-8 -*-
"""SQLite 访问层。

设计取舍：
- 不用 ORM：演示数据量小，标准库 sqlite3 足够，依赖更少；
- 每次操作独立连接 + WAL：单 worker 下读写互不阻塞，避免长连接跨线程问题；
- 写操作显式事务：确认单落库时保证「工单 + 审计」原子性。
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from backend.core.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('buyer', 'operator', 'supervisor')),
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT '',
    price REAL NOT NULL,
    original_price REAL NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    sales_7d INTEGER NOT NULL DEFAULT 0,
    rating REAL NOT NULL DEFAULT 0,
    sales_total INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    attributes TEXT NOT NULL DEFAULT '{}',
    description TEXT NOT NULL DEFAULT '',
    sku_summary TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    special INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,
    discount REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL,
    receiver_name TEXT NOT NULL DEFAULT '',
    receiver_phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    paid_at TEXT,
    shipped_at TEXT,
    signed_at TEXT,
    logistics_company TEXT,
    tracking_no TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES products(id),
    title TEXT NOT NULL,
    price REAL NOT NULL,
    qty INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS logistics (
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    time TEXT NOT NULL,
    status TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (order_id, seq)
);

CREATE TABLE IF NOT EXISTS coupons (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('fixed', 'percent')),
    threshold REAL NOT NULL DEFAULT 0,
    discount REAL NOT NULL,
    max_discount REAL,
    scope_category TEXT,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    stackable INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS user_coupons (
    user_id TEXT NOT NULL REFERENCES users(id),
    coupon_id TEXT NOT NULL REFERENCES coupons(id),
    used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, coupon_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL DEFAULT '-',
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_logistics_order ON logistics(order_id);
CREATE INDEX IF NOT EXISTS idx_tickets_order ON tickets(order_id);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or get_settings().db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def parse_json(value: str, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


def db_ready() -> bool:
    try:
        with get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        return count > 0
    except sqlite3.Error:
        return False
