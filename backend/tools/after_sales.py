# -*- coding: utf-8 -*-
"""售后工具：政策检索、资格判定、工单创建（确认制）、转人工。"""
from __future__ import annotations

from langchain_core.tools import tool

from backend.services import after_sales, knowledge
from backend.services.identity import Identity


def build_after_sales_tools(identity: Identity) -> list:
    @tool(
        "search_after_sales_policy",
        response_format="content_and_artifact",
        description=(
            "检索退换货、物流、优惠券、发票保修等平台政策。"
            "回答售后规则前必须调用；回答时要引用返回的条款来源，不要自行编造政策。"
        ),
    )
    def search_after_sales_policy(question: str) -> tuple[str, dict]:
        chunks = knowledge.search_policies(question, top_k=3)
        if not chunks:
            return (
                "政策库未覆盖这个问题，无法给出确定结论。建议转人工客服确认。",
                {"card_type": "sources", "data": {"items": []}, "sources": []},
            )

        sources = [
            {
                "title": f"{c['source']}#{c['section']}",
                "source": c["source"],
                "snippet": c["text"][:240],
            }
            for c in chunks
        ]
        lines = ["政策库检索结果（回答时请引用来源）："]
        for chunk in chunks:
            lines.append(f"【{chunk['source']} · {chunk['section']}】\n{chunk['text'][:420]}")
        return "\n\n".join(lines), {
            "card_type": "sources",
            "data": {"items": sources},
            "sources": sources,
        }

    @tool(
        "check_return_eligibility",
        response_format="content_and_artifact",
        description=(
            "判定订单是否满足退换/维修条件。返回是否可退、依据、签收天数和替代方案。"
            "用户问「能退吗/能换吗/还在保修期吗」时先调用此工具，不要自行判断。"
            "opened 表示商品是否已拆封使用：只有用户明确说已拆封/已使用/已激活时才传 true，"
            "未提及一律用默认值 false，不要自行假设。reason 填用户描述的原因。"
        ),
    )
    def check_return_eligibility(
        order_id: str, reason: str, opened: bool = False
    ) -> tuple[str, dict]:
        result = after_sales.evaluate(order_id.strip(), identity, reason, opened=opened)
        lines = [
            f"订单 {result['order_id']}｜商品：{result['product_title']}",
            f"结论：{'可以申请' if result['eligible'] else '暂不支持'} {result['type']}",
            f"签收天数：{result['days_since_signed']} 天｜是否拆封：{'是' if result['opened'] else '否'}",
            "依据：" + "；".join(result["reasons"]),
        ]
        if result["alternatives"]:
            lines.append("替代方案：" + "；".join(result["alternatives"]))
        sources = [
            {"title": ref, "source": ref.split("#")[0], "snippet": ref}
            for ref in result["policy_refs"]
        ]
        return "\n".join(lines), {
            "card_type": "eligibility",
            "data": result,
            "sources": sources,
        }

    @tool(
        "create_after_sales_ticket",
        response_format="content_and_artifact",
        description=(
            "为订单创建售后工单。必须先生成确认单，用户在前端点击确认后才会真正落库。"
            "ticket_type 只能是 return（退货）、exchange（换货）、repair（维修）、complaint（投诉）。"
            "退货/换货要求资格判定通过；维修要求属于质量问题或保修期内。"
            "opened 只有用户明确说已拆封/已使用/已激活时才传 true，未提及一律用默认值 false。"
        ),
    )
    def create_after_sales_ticket(
        order_id: str,
        ticket_type: str,
        reason: str,
        opened: bool = False,
    ) -> tuple[str, dict]:
        result = after_sales.request_ticket(
            identity,
            order_id.strip(),
            ticket_type.strip().lower(),
            reason,
            opened=opened,
        )
        if not result.get("ok"):
            return after_sales.ticket_text(result), {
                "card_type": "eligibility",
                "data": result.get("eligibility", {}),
                "sources": [],
            }

        pending = result["pending_action"]
        data = {
            **pending,
            "order_id": order_id,
            "ticket_type": ticket_type,
            "reason": reason,
            "eligibility": result["eligibility"],
        }
        return after_sales.ticket_text(result), {
            "card_type": "pending_action",
            "data": data,
            "sources": [],
        }

    @tool(
        "handoff_to_human",
        response_format="content_and_artifact",
        description=(
            "转人工客服。当政策库未覆盖、用户明确要求人工、或情绪激动/争议较大时调用。"
            "reason 简要说明转人工原因。"
        ),
    )
    def handoff_to_human(reason: str) -> tuple[str, dict]:
        result = after_sales.handoff(identity, reason)
        return result["message"], {
            "card_type": "handoff",
            "data": result,
            "sources": [],
        }

    return [
        search_after_sales_policy,
        check_return_eligibility,
        create_after_sales_ticket,
        handoff_to_human,
    ]
