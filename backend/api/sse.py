# -*- coding: utf-8 -*-
"""SSE 编码与异常转换。

前端使用 fetch + ReadableStream 读取（EventSource 不支持 POST）。
每条消息格式：
    event: token
    data: {"text": "..."}

"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from backend.core.errors import AppError

logger = logging.getLogger(__name__)


def _encode(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _wrap(events: AsyncIterator[tuple[str, dict]]) -> AsyncIterator[str]:
    try:
        async for event, data in events:
            yield _encode(event, data)
    except AppError as exc:
        yield _encode("error", {"code": exc.code, "message": exc.message})
    except Exception as exc:  # pragma: no cover - 兜底，避免连接悬挂
        logger.exception("流式响应异常: %s", exc)
        yield _encode("error", {"code": "INTERNAL_ERROR", "message": "生成回答时出现错误，请稍后重试"})


def sse_response(events: AsyncIterator[tuple[str, dict]]) -> StreamingResponse:
    return StreamingResponse(
        _wrap(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
