# -*- coding: utf-8 -*-
"""请求 / 响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    session_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="会话 id，用于隔离多轮记忆",
    )


class AgentResponse(BaseModel):
    answer: str
    tool_calls: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    cards: list[dict] = Field(default_factory=list)
    truncated: bool = False


class ActionResponse(BaseModel):
    status: str
    token: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str = ""
