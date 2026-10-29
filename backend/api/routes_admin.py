# -*- coding: utf-8 -*-
"""管理接口：索引重建、统计、配置摘要。"""
from __future__ import annotations

import anyio
from fastapi import APIRouter, Depends

from backend.api.deps import require_api_key
from backend.core.config import get_settings
from backend.services.db import db_ready, get_conn
from backend.services.knowledge import build_index, index_stats

router = APIRouter(prefix="/api", tags=["admin"])


@router.post(
    "/ingest",
    dependencies=[Depends(require_api_key)],
    summary="重建商品与政策向量索引",
)
async def ingest() -> dict:
    return await anyio.to_thread.run_sync(build_index)


@router.get(
    "/stats",
    dependencies=[Depends(require_api_key)],
    summary="索引与数据统计",
)
async def stats() -> dict:
    counts = {}
    if db_ready():
        with get_conn() as conn:
            for table in ("products", "orders", "tickets", "coupons"):
                counts[table] = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    return {
        "index": index_stats(),
        "db": {"ready": db_ready(), "counts": counts},
        "llm_ready": get_settings().chat_ready,
        "auth_enabled": get_settings().auth_enabled,
    }


@router.get(
    "/meta",
    dependencies=[Depends(require_api_key)],
    summary="可安全暴露的配置摘要（不含密钥）",
)
async def meta() -> dict:
    settings = get_settings()
    return {
        "app_env": settings.app_env,
        "llm_model": settings.llm_model,
        "embed_model": settings.embed_model,
        "embedding_enabled": settings.embedding_enabled,
        "auth_enabled": settings.auth_enabled,
        "demo_role_header_enabled": settings.demo_role_header_enabled,
        "default_buyer": "u_buyer_001",
        "default_operator": "u_ops_001",
    }
