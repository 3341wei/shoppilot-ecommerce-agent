# -*- coding: utf-8 -*-
"""Agent 编排测试：用脚本化假模型验证「工具调用 → 富卡片 → 最终回答」链路，不联网。"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from backend.services import agent as agent_module
from backend.services.identity import Identity
from backend.tools import build_tools


class ScriptedChatModel(BaseChatModel):
    """按顺序返回预设消息；bind_tools 直接返回自身。"""

    responses: list[Any]
    index: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def _buyer() -> Identity:
    return Identity("u_buyer_001", "buyer", f"agent_test_{uuid.uuid4().hex[:8]}")


def test_agent_stream_emits_tool_card_sources_and_answer(monkeypatch):
    fake = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_products",
                        "args": {"query": "轻量缓震跑步鞋", "max_price": 500},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="推荐轻量缓震跑步鞋 P2001，到手价 339 元。"),
        ]
    )
    monkeypatch.setattr(agent_module, "get_llm", lambda: fake)

    async def collect():
        return [
            (event, data)
            async for event, data in agent_module.run_stream("推荐一双 500 以内的跑鞋", _buyer())
        ]

    events = asyncio.run(collect())
    names = [event for event, _ in events]

    assert names[0] == "tool"
    assert names[-1] == "done"

    tool_event = next(data for event, data in events if event == "tool")
    assert tool_event["name"] == "search_products"

    card = next(data for event, data in events if event == "tool_result")
    assert card["card_type"] == "products"
    assert card["data"]["products"][0]["id"] == "P2001"

    tokens = "".join(data["text"] for event, data in events if event == "token")
    assert "P2001" in tokens

    done = next(data for event, data in events if event == "done")
    assert "P2001" in done["answer"]
    assert done["truncated"] is False
    assert done["sources"]


def test_agent_http_sse_end_to_end(client, monkeypatch):
    """HTTP + SSE 全链路：假模型 → 工具 → 卡片事件 → 最终回答。"""
    from backend.api import routes_agent

    fake = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_products",
                        "args": {"query": "轻量缓震跑步鞋", "max_price": 500},
                        "id": "call_http",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="推荐 P2001。"),
        ]
    )
    monkeypatch.setattr(agent_module, "get_llm", lambda: fake)
    monkeypatch.setattr(routes_agent, "_ensure_ready", lambda: None)

    response = client.post(
        "/api/agent/stream",
        json={"question": "推荐一双跑鞋", "session_id": f"http_{uuid.uuid4().hex[:8]}"},
        headers={"X-User-Role": "buyer", "X-User-Id": "u_buyer_001"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    body = response.text
    assert "event: tool" in body
    assert "event: tool_result" in body
    assert '"card_type": "products"' in body
    assert "event: token" in body
    assert "event: done" in body


def test_role_tool_isolation():
    buyer_tools = {tool.name for tool in build_tools(_buyer())}
    operator_tools = {tool.name for tool in build_tools(Identity("u_ops_001", "operator", "s"))}

    assert "get_order" in buyer_tools
    assert "track_logistics" in buyer_tools
    assert "create_after_sales_ticket" in buyer_tools
    assert "get_sales_overview" not in buyer_tools
    assert "get_inventory_alerts" not in buyer_tools

    assert "get_sales_overview" in operator_tools
    assert "get_inventory_alerts" in operator_tools
    assert "get_order" not in operator_tools
    assert "create_after_sales_ticket" not in operator_tools
