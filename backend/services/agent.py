# -*- coding: utf-8 -*-
"""Agent 服务：按角色装配工具，LangGraph 负责工具循环与会话记忆。

每个请求构建一次 Agent（工具闭包捕获当前身份），代价很小，但换来了：
- 工具集严格按角色隔离；
- 工具内可直接拿到 user_id / session_id，不需要全局变量或上下文猜测；
- 并发请求之间不会串身份。

会话记忆由进程内 MemorySaver 保存，因此服务以单 worker 运行。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError

from backend.core.config import get_settings
from backend.services.identity import Identity
from backend.services.llm import extract_text, get_llm
from backend.tools import build_tools

logger = logging.getLogger(__name__)

_checkpointer = MemorySaver()

SYSTEM_PROMPTS = {
    "buyer": (
        "你是 ShopPilot 电商客服助手，服务对象是当前登录的买家。\n"
        "工作规则：\n"
        "1. 商品、订单、物流、售后问题必须调用工具获取事实，不要编造价格、库存、订单状态和时效。\n"
        "2. 售后问题先调用 search_after_sales_policy 查政策，再调用 check_return_eligibility 判定；回答要引用政策来源。\n"
        "3. 创建工单属于写操作：调用 create_after_sales_ticket 只会生成确认单，"
        "必须提示用户「请点击确认卡片」，不要声称已经创建成功。\n"
        "4. 只能查询当前用户自己的订单；工具返回无权查询时，如实告知并建议核对订单号。\n"
        "5. 不要承诺工具没有返回的赔付金额、退款时效或库存。\n"
        "6. 回答先给结论，再给依据；金额保留两位小数；手机号和地址只展示工具返回的脱敏结果。\n"
        "7. 判定售后资格或创建工单时，只有用户明确说商品已拆封/已使用/已激活，"
        "才把 opened 设为 true；用户没提就保持默认 false，不要自行假设已拆封。\n"
        "8. 语气亲切、简洁，不寒暄过多。\n"
    ),
    "operator": (
        "你是 ShopPilot 电商运营数据助手，服务对象是运营人员。\n"
        "工作规则：\n"
        "1. 销售、退款率、库存问题必须调用工具取数，不要编造指标。\n"
        "2. 先给结论，再给数据与口径；明确区分「数据事实」和「可能原因/推测」。\n"
        "3. 用户给相对时间（上周、本月）时，先调用 get_current_time 确定当前日期，再换算查询区间。\n"
        "4. 指标异常时给出可执行的下钻建议或补货建议，但不要假装执行了调价、补货等操作。\n"
        "5. 回答简洁，金额保留两位小数，百分比保留一位小数。\n"
    ),
}


def _thread_id(identity: Identity) -> str:
    return f"{identity.user_id}:{identity.session_id}"


def _config(identity: Identity) -> dict:
    settings = get_settings()
    return {
        "configurable": {"thread_id": _thread_id(identity)},
        # 每轮工具调用至少消耗 2 个图节点，留出余量后强制终止，避免死循环烧 token
        "recursion_limit": settings.agent_max_tool_calls * 2 + 2,
    }


def build_agent(identity: Identity):
    return create_agent(
        get_llm(),
        build_tools(identity),
        system_prompt=SYSTEM_PROMPTS.get(identity.role, SYSTEM_PROMPTS["buyer"]),
        checkpointer=_checkpointer,
    )


def forget_session(identity: Identity) -> None:
    try:
        _checkpointer.delete_thread(_thread_id(identity))
    except Exception as exc:  # pragma: no cover - 取决于 checkpointer 实现
        logger.warning("清理会话失败: %s", exc)


def _sources_from_artifact(artifact) -> list[dict]:
    if not isinstance(artifact, dict):
        return []
    sources = artifact.get("sources")
    return [item for item in sources if isinstance(item, dict)] if isinstance(sources, list) else []


async def run_stream(
    question: str, identity: Identity
) -> AsyncIterator[tuple[str, dict]]:
    """事件：tool → tool_result* → reset? → token* → sources → done。"""
    agent = build_agent(identity)
    config = _config(identity)

    parts: list[str] = []
    tool_calls: list[str] = []
    sources: list[dict] = []
    cards: list[dict] = []
    seen_sources: set[tuple] = set()

    try:
        async for mode, data in agent.astream(
            {"messages": [("user", question)]},
            config=config,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                chunk, _metadata = data
                text = extract_text(getattr(chunk, "content", None))
                # 兼容流式 chunk 与不支持流式的模型（后者在 messages 模式下返回完整 AIMessage）
                if text and isinstance(chunk, (AIMessage, AIMessageChunk)):
                    parts.append(text)
                    yield "token", {"text": text}

            elif mode == "updates":
                for update in data.values():
                    messages = update.get("messages", []) if isinstance(update, dict) else []
                    for msg in messages:
                        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                            if parts:
                                parts.clear()
                                yield "reset", {"reason": "tool_call"}
                            for call in msg.tool_calls:
                                name = call.get("name") if isinstance(call, dict) else None
                                if name and name not in tool_calls:
                                    tool_calls.append(name)
                                    yield "tool", {"name": name}

                        if isinstance(msg, ToolMessage) and isinstance(msg.artifact, dict):
                            artifact = msg.artifact
                            for source in _sources_from_artifact(artifact):
                                key = (source.get("source"), source.get("title"))
                                if key in seen_sources:
                                    continue
                                seen_sources.add(key)
                                sources.append(source)
                            card_type = artifact.get("card_type")
                            if card_type:
                                card = {
                                    "card_type": card_type,
                                    "data": artifact.get("data", {}),
                                    "sources": artifact.get("sources", []),
                                }
                                cards.append(card)
                                yield "tool_result", {
                                    "name": getattr(msg, "name", ""),
                                    **card,
                                }
    except GraphRecursionError:
        logger.warning("工具调用次数超限，终止本轮")
        fallback = "这个问题需要的信息较多，已超过单轮查询上限。请缩小问题范围，或转人工客服继续处理。"
        if not parts:
            parts.append(fallback)
            yield "token", {"text": fallback}
        yield "sources", {"sources": sources}
        yield "done", {
            "answer": fallback,
            "tool_calls": tool_calls,
            "sources": sources,
            "cards": cards,
            "truncated": True,
        }
        return

    yield "sources", {"sources": sources}
    yield "done", {
        "answer": "".join(parts).strip(),
        "tool_calls": tool_calls,
        "sources": sources,
        "cards": cards,
        "truncated": False,
    }


async def run_collect(question: str, identity: Identity) -> dict:
    final: dict = {"answer": "", "tool_calls": [], "sources": [], "cards": []}
    async for event, data in run_stream(question, identity):
        if event == "done":
            final = data
    return final
