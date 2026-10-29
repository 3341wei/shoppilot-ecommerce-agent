# -*- coding: utf-8 -*-
"""请求身份。

演示环境通过请求头传递身份：
- X-User-Role: buyer / operator
- X-User-Id:   演示用户 id

生产环境必须改为从 JWT/OAuth 解析，绝不能让客户端自报角色。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.core.errors import ForbiddenError

_ROLE_ALIASES = {"buyer": "buyer", "customer": "buyer", "operator": "operator", "ops": "operator"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DEFAULT_BUYER = "u_buyer_001"
DEFAULT_OPERATOR = "u_ops_001"


@dataclass(frozen=True)
class Identity:
    user_id: str
    role: str
    session_id: str = "default"
    name: str = ""

    @property
    def is_operator(self) -> bool:
        return self.role == "operator"


def build_identity(
    user_id: str | None,
    role: str | None,
    session_id: str | None,
    *,
    enabled: bool = True,
) -> Identity:
    if not enabled:
        raise ForbiddenError("演示身份入口已关闭，请接入正式登录体系")

    normalized_role = _ROLE_ALIASES.get((role or "buyer").strip().lower(), "")
    if not normalized_role:
        raise ForbiddenError("无效的角色，仅支持 buyer / operator")

    default_id = DEFAULT_OPERATOR if normalized_role == "operator" else DEFAULT_BUYER
    final_id = (user_id or default_id).strip()
    if not _ID_RE.match(final_id):
        raise ForbiddenError("无效的用户 id")

    final_session = (session_id or "default").strip()
    if not _SESSION_RE.match(final_session):
        raise ForbiddenError("无效的会话 id")

    return Identity(user_id=final_id, role=normalized_role, session_id=final_session)
