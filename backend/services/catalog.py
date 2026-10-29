# -*- coding: utf-8 -*-
"""商品服务：查询、格式化、检索文本。"""
from __future__ import annotations

from backend.core.errors import NotFoundError
from backend.services.db import get_conn, parse_json, rows_to_dicts

_CARD_FIELDS = {
    "id", "title", "category", "brand", "price", "original_price", "stock",
    "rating", "sales_total", "tags", "attributes", "sku_summary", "image", "special",
}


def _to_product(row) -> dict:
    product = dict(row)
    product["tags"] = parse_json(product.get("tags", "[]"), [])
    product["attributes"] = parse_json(product.get("attributes", "{}"), {})
    product["price"] = float(product["price"])
    product["original_price"] = float(product["original_price"])
    product["in_stock"] = int(product["stock"]) > 0
    product["special"] = bool(product["special"])
    return product


def get_product(product_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"商品 {product_id} 不存在")
    return _to_product(row)


def find_products(
    *,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    in_stock: bool = False,
    limit: int = 100,
) -> list[dict]:
    sql = "SELECT * FROM products WHERE 1=1"
    params: list = []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if min_price is not None:
        sql += " AND price >= ?"
        params.append(min_price)
    if max_price is not None:
        sql += " AND price <= ?"
        params.append(max_price)
    if in_stock:
        sql += " AND stock > 0"
    sql += " ORDER BY sales_total DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_to_product(row) for row in rows]


def list_categories() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()
    return [row["category"] for row in rows]


def product_text(product: dict) -> str:
    attrs = "；".join(f"{k}：{v}" for k, v in product["attributes"].items())
    tags = "、".join(product["tags"])
    return (
        f"商品：{product['title']}（{product['id']}）\n"
        f"类目：{product['category']}｜品牌：{product['brand']}\n"
        f"价格：{product['price']:.0f} 元（原价 {product['original_price']:.0f} 元）\n"
        f"标签：{tags}\n参数：{attrs}\n"
        f"库存：{product['stock']} 件｜评分：{product['rating']}\n"
        f"卖点：{product['description']}"
    )


def to_card(product: dict) -> dict:
    card = {key: product[key] for key in _CARD_FIELDS if key in product}
    card["in_stock"] = product.get("in_stock", int(product.get("stock", 0)) > 0)
    return card


def brief(product: dict) -> str:
    stock = f"有货（{product['stock']} 件）" if product["in_stock"] else "缺货"
    return (
        f"{product['id']} {product['title']}｜{product['category']}｜"
        f"¥{product['price']:.0f}｜评分 {product['rating']}｜{stock}"
    )


def public_catalog() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY category, id").fetchall()
    return rows_to_dicts(rows)
