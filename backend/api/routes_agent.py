# -*- coding: utf-8 -*-
"""Agent 问答接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from backend.api.deps import (
    IdentityHeaders,
    build_request_identity,
    get_identity_headers,
    require_api_key,
)
from backend.api.sse import sse_response
from backend.core.config import get_settings
from backend.core.errors import BadRequestError, ServiceUnavailableError
from backend.schemas import AgentResponse, ChatRequest
from backend.services.agent import forget_session, run_collect, run_stream

router = APIRouter(prefix="/api", tags=["agent"])


def _ensure_ready() -> None:
    if not get_settings().chat_ready:
        raise ServiceUnavailableError(
            "未配置 DEEPSEEK_API_KEY，智能体暂不可用。请参考 .env.example 补齐配置。"
        )


@router.post(
    "/agent",
    response_model=AgentResponse,
    dependencies=[Depends(require_api_key)],
    summary="智能体问答（非流式）",
)
async def agent_chat(
    req: ChatRequest, headers: IdentityHeaders = Depends(get_identity_headers)
) -> dict:
    _ensure_ready()
    identity = build_request_identity(headers, req.session_id)
    return await run_collect(req.question, identity)


@router.post(
    "/agent/stream",
    dependencies=[Depends(require_api_key)],
    summary="智能体问答（SSE 流式）",
)
async def agent_stream(
    req: ChatRequest, headers: IdentityHeaders = Depends(get_identity_headers)
):
    _ensure_ready()
    if not get_settings().stream_enabled:
        raise BadRequestError("流式接口未启用")
    identity = build_request_identity(headers, req.session_id)
    return sse_response(run_stream(req.question, identity))


@router.delete(
    "/agent/session/{session_id}",
    dependencies=[Depends(require_api_key)],
    summary="清空某个会话的 Agent 记忆",
)
def delete_session(
    session_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    headers: IdentityHeaders = Depends(get_identity_headers),
) -> dict:
    identity = build_request_identity(headers, session_id, require_session=True)
    forget_session(identity)
    return {"status": "ok", "session_id": session_id}
