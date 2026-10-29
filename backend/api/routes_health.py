# -*- coding: utf-8 -*-
"""健康探针。"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.config import get_settings
from backend.services.db import db_ready
from backend.services.knowledge import index_stats

router = APIRouter(tags=["health"])
APP_VERSION = "1.0.0"


@router.get("/healthz", summary="存活探针")
def healthz() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@router.get("/readyz", summary="就绪探针：配置 / 数据库 / 索引")
def readyz() -> JSONResponse:
    settings = get_settings()
    checks = {
        "llm_key": bool(settings.llm_api_key),
        "database": db_ready(),
        "auth": (not settings.is_production) or settings.auth_enabled,
    }
    try:
        checks["index"] = index_stats()
    except Exception:
        checks["index"] = {"error": "unavailable"}

    ready = checks["llm_key"] and checks["database"] and checks["auth"]
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "version": APP_VERSION,
            "checks": checks,
            "hint": "" if ready else "请先执行 python scripts/seed_db.py，并配置 DEEPSEEK_API_KEY",
        },
    )
