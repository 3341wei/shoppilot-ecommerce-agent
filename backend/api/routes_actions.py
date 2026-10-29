# -*- coding: utf-8 -*-
"""写操作确认接口。

确认时重新校验身份与会话归属，不依赖前端传入的 user_id。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Path

from backend.api.deps import (
    IdentityHeaders,
    build_request_identity,
    get_identity_headers,
    require_api_key,
)
from backend.services import actions

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.post(
    "/{token}/confirm",
    dependencies=[Depends(require_api_key)],
    summary="确认并执行待确认操作",
)
def confirm_action(
    token: str = Path(..., min_length=8, max_length=128),
    headers: IdentityHeaders = Depends(get_identity_headers),
    x_session_id: str = Header(default="", alias="X-Session-Id"),
) -> dict:
    identity = build_request_identity(headers, x_session_id, require_session=True)
    return actions.confirm(token, identity)


@router.post(
    "/{token}/cancel",
    dependencies=[Depends(require_api_key)],
    summary="取消待确认操作",
)
def cancel_action(
    token: str = Path(..., min_length=8, max_length=128),
    headers: IdentityHeaders = Depends(get_identity_headers),
    x_session_id: str = Header(default="", alias="X-Session-Id"),
) -> dict:
    identity = build_request_identity(headers, x_session_id, require_session=True)
    return actions.cancel(token, identity)
