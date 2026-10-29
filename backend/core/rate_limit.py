# -*- coding: utf-8 -*-
"""滑动窗口限流（进程内）。

单 worker 部署下足够；多实例部署需换 Redis 原子计数。
按客户端 IP + 路径前缀分桶，普通接口与 ingest 使用不同配额。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.core.config import Settings, get_settings
from backend.core.context import get_request_id

_WINDOW_STORE: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()


def _client_key(request: Request, trust_proxy: bool = False) -> str:
    # 默认只信任 TCP 对端地址；反向代理场景需显式开启 TRUST_PROXY_HEADERS
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _consume(key: tuple[str, str], limit: int, window: int) -> tuple[bool, int]:
    now = time.monotonic()
    with _LOCK:
        bucket = _WINDOW_STORE[key]
        while bucket and now - bucket[0] >= window:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window - (now - bucket[0])) + 1)
            return False, retry_after
        bucket.append(now)
        return True, 0


def reset_rate_limits() -> None:
    with _LOCK:
        _WINDOW_STORE.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings | None = None) -> None:
        super().__init__(app)
        self.settings = settings or get_settings()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in {"/healthz", "/readyz"} or request.method == "OPTIONS":
            return await call_next(request)

        is_ingest = request.url.path == "/api/ingest"
        limit = (
            self.settings.ingest_rate_limit_requests
            if is_ingest
            else self.settings.rate_limit_requests
        )
        window = (
            self.settings.ingest_rate_limit_window_seconds
            if is_ingest
            else self.settings.rate_limit_window_seconds
        )
        allowed, retry_after = _consume(
            (
                _client_key(request, self.settings.trust_proxy_headers),
                "ingest" if is_ingest else "api",
            ),
            limit,
            window,
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"请求过于频繁，请 {retry_after} 秒后重试",
                        "request_id": get_request_id(),
                    }
                },
            )
        return await call_next(request)
