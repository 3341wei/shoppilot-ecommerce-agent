# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

    python run.py
    uvicorn backend.main:app
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import routes_actions, routes_admin, routes_agent, routes_health
from backend.core.config import ROOT_DIR, get_settings
from backend.core.errors import register_exception_handlers
from backend.core.logging import configure_logging
from backend.core.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from backend.core.rate_limit import RateLimitMiddleware
from backend.services.db import init_db
from backend.services.knowledge import invalidate_index_cache
from backend.services.llm import reset_llm

logger = logging.getLogger(__name__)

APP_TITLE = "ShopPilot 电商业务智能体"
APP_VERSION = "1.0.0"
MAX_BODY_BYTES = 64 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.started_at = time.time()
    init_db()

    logger.info(
        "服务启动 | env=%s | llm=%s | embedding=%s | auth=%s",
        settings.app_env,
        settings.llm_model,
        "on" if settings.embedding_enabled else "off(BM25 only)",
        "on" if settings.auth_enabled else "off",
    )
    if settings.missing_required_keys:
        logger.warning(
            "缺少配置：%s。相关接口会返回 503，请参考 .env.example 补齐",
            "、".join(settings.missing_required_keys),
        )

    yield

    logger.info("服务关闭，释放资源")
    reset_llm()
    invalidate_index_cache()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    docs_url = None if settings.is_production else "/docs"
    openapi_url = None if settings.is_production else "/openapi.json"

    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        description="FastAPI + LangChain + SQLite/ChromaDB 的电商业务 Agent",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
    )

    # 后添加的中间件位于更外层：CORS → 请求上下文 → 安全头 → 限流 → 体积限制
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key", "X-User-Id", "X-User-Role", "X-Session-Id"],
            allow_credentials=False,
        )

    register_exception_handlers(app)

    app.include_router(routes_health.router)
    app.include_router(routes_agent.router)
    app.include_router(routes_actions.router)
    app.include_router(routes_admin.router)

    frontend_dir = ROOT_DIR / "frontend"
    if frontend_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()
