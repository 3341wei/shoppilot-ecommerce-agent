# -*- coding: utf-8 -*-
"""接口依赖：API Key 校验与演示身份解析。"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header

from backend.core.config import get_settings
from backend.core.errors import UnauthorizedError
from backend.core.security import constant_time_equals
from backend.services.identity import Identity, build_identity


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        return
    if not x_api_key or not any(
        constant_time_equals(x_api_key, expected) for expected in settings.api_keys
    ):
        raise UnauthorizedError("访问密钥无效")


@dataclass(frozen=True)
class IdentityHeaders:
    user_id: str | None
    role: str | None


def get_identity_headers(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> IdentityHeaders:
    return IdentityHeaders(user_id=x_user_id, role=x_user_role)


def build_request_identity(
    headers: IdentityHeaders, session_id: str, *, require_session: bool = False
) -> Identity:
    settings = get_settings()
    session = session_id.strip() if session_id else ""
    if require_session and not session:
        from backend.core.errors import BadRequestError

        raise BadRequestError("缺少会话 id，无法校验确认操作归属")
    return build_identity(
        headers.user_id,
        headers.role,
        session or "default",
        enabled=settings.demo_role_header_enabled,
    )
