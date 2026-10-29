# -*- coding: utf-8 -*-
"""商品域工具：搜索、详情、库存、到手价。"""
from __future__ import annotations

from langchain_core.tools import tool

from backend.services import catalog, knowledge, promotions, rules
from backend.services.identity import Identity


def _sources(product: dict) -> list[dict]:
    return [
        {
            "title": product["title"],
            "source": f"商品库#{product['id']}",
            "snippet": product.get("description", "")[:160],
        }
    ]


def build_product_tools(identity: Identity) -> list:
    @tool(
        "search_products",
        response_format="content_and_artifact",
        description=(
            "按自然语言和硬条件搜索在售商品。用户问「有什么/推荐/多少钱/适合…」时调用。"
            "category 可选：数码、运动户外、家居；max_price 为价格上限（0 表示不限）；"
            "in_stock 默认 True，只返回有货商品。返回商品卡片与来源。"
        ),
    )
    def search_products(
        query: str,
        category: str = "",
        max_price: float = 0,
        in_stock: bool = True,
    ) -> tuple[str, dict]:
        results = knowledge.search_products(
            query,
            category=category or None,
            max_price=max_price if max_price and max_price > 0 else None,
            in_stock=in_stock,
            top_k=5,
        )
        if not results:
            return (
                "没有找到符合条件的商品。建议放宽价格或类目条件，或换一种描述。",
                {"card_type": "products", "data": {"products": []}, "sources": []},
            )

        products = [item["product"] for item in results]
        lines = [f"找到 {len(products)} 个符合条件的商品："]
        lines.extend(f"- {catalog.brief(p)}" for p in products)
        lines.append("以上商品均来自商品库，价格与库存为当前快照。")

        sources: list[dict] = []
        for product in products:
            sources.extend(_sources(product))
        return (
            "\n".join(lines),
            {
                "card_type": "products",
                "data": {"products": [catalog.to_card(p) for p in products]},
                "sources": sources,
            },
        )

    @tool(
        "get_product_detail",
        response_format="content_and_artifact",
        description="查询单个商品的完整参数、库存、评分与适用场景。已知商品 id 或用户指定某款商品时调用。",
    )
    def get_product_detail(product_id: str) -> tuple[str, dict]:
        product = catalog.get_product(product_id)
        attrs = "；".join(f"{k}：{v}" for k, v in product["attributes"].items())
        stock_text = f"有货（{product['stock']} 件）" if product["in_stock"] else "暂时缺货"
        text = (
            f"{product['title']}（{product['id']}）\n"
            f"类目：{product['category']}｜品牌：{product['brand']}\n"
            f"价格：¥{product['price']:.0f}（原价 ¥{product['original_price']:.0f}）\n"
            f"参数：{attrs}\n库存：{stock_text}｜评分：{product['rating']}｜累计销量：{product['sales_total']}\n"
            f"卖点：{product['description']}"
        )
        return text, {
            "card_type": "product",
            "data": {"product": catalog.to_card(product)},
            "sources": _sources(product),
        }

    @tool(
        "check_stock",
        response_format="content_and_artifact",
        description="查询商品库存与补货建议。用户问「还有货吗/库存多少/什么时候补货」时调用。",
    )
    def check_stock(product_id: str) -> tuple[str, dict]:
        product = catalog.get_product(product_id)
        status = rules.inventory_status(product["stock"], product["sales_7d"])
        if status["level"] == "out":
            text = (
                f"{product['title']} 当前缺货。"
                f"参考近 7 日销量，建议补货约 {max(status['suggested_replenish'], 1)} 件。"
            )
        elif status["level"] in {"critical", "warning"}:
            text = (
                f"{product['title']} 库存 {product['stock']} 件（{status['label']}），"
                f"安全库存约 {status['safety_stock']} 件，建议尽快补货。"
            )
        else:
            text = f"{product['title']} 库存充足，当前 {product['stock']} 件。"
        return text, {
            "card_type": "stock",
            "data": {"product": catalog.to_card(product), "inventory": status},
            "sources": _sources(product),
        }

    @tool(
        "calc_best_price",
        response_format="content_and_artifact",
        description=(
            "试算商品到手价，自动组合当前用户可用的店铺券、平台券、品类券，返回优惠明细。"
            "用户问「多少钱/有优惠吗/到手价」时调用。qty 默认 1。"
        ),
    )
    def calc_best_price(product_id: str, qty: int = 1) -> tuple[str, dict]:
        data = promotions.calculate_price(product_id, max(1, qty), identity.user_id)
        return promotions.price_text(data), {
            "card_type": "price",
            "data": promotions.to_card(data),
            "sources": _sources(data["product"]),
        }

    return [search_products, get_product_detail, check_stock, calc_best_price]
