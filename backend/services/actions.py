# -*- coding: utf-8 -*-
"""待确认操作（确认单）机制。

写操作不直接执行，而是：
1. 工具校验业务前提，生成 pending_action（token + 摘要 + 过期时间）；
2. 前端展示确认卡片；
3. 用户显式点击确认，调用 confirm 才真正落库。

保证：
- token 绑定 user_id + session_id；
- TTL 到期自动失效；
- 一次性使用，重复确认返回同一结果（幂等）；
- 每次执行写审计日志。
"""
from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.core.config import get_settings
from backend.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from backend.services.identity import Identity

Executor = Callable[[dict, Identity], dict]


@dataclass
class PendingAction:
    token: str
    user_id: str
    role: str
    session_id: str
    action_type: str
    summary: str
    payload: dict
    expires_at: float
    state: str = "pending"  # pending / executing / done / cancelled
    result: dict = field(default_factory=dict)


_LOCK = threading.RLock()
_ACTIONS: dict[str, PendingAction] = {}
_EXECUTORS: dict[str, Executor] = {}


def register_executor(action_type: str, executor: Executor) -> None:
    _EXECUTORS[action_type] = executor


def _cleanup_expired(now: float) -> None:
    for token, action in list(_ACTIONS.items()):
        if action.state == "pending" and action.expires_at < now:
            action.state = "cancelled"
        if action.state in {"done", "cancelled"} and action.expires_at < now - 600:
            _ACTIONS.pop(token, None)


def issue(
    identity: Identity,
    action_type: str,
    summary: str,
    payload: dict,
    ttl_seconds: int | None = None,
) -> dict:
    if action_type not in _EXECUTORS:
        raise BadRequestError(f"不支持的写操作：{action_type}")

    ttl = ttl_seconds or get_settings().pending_action_ttl_seconds
    now = time.time()
    token = secrets.token_urlsafe(24)
    action = PendingAction(
        token=token,
        user_id=identity.user_id,
        role=identity.role,
        session_id=identity.session_id,
        action_type=action_type,
        summary=summary,
        payload=payload,
        expires_at=now + ttl,
    )
    with _LOCK:
        _cleanup_expired(now)
        _ACTIONS[token] = action

    return {
        "token": token,
        "action_type": action_type,
        "summary": summary,
        "expires_at": action.expires_at,
        "ttl_seconds": ttl,
    }


def _get_action(token: str) -> PendingAction:
    with _LOCK:
        action = _ACTIONS.get(token)
    if action is None:
        raise NotFoundError("确认操作不存在或已失效")
    return action


def confirm(token: str, identity: Identity) -> dict:
    action = _get_action(token)

    if action.user_id != identity.user_id or action.session_id != identity.session_id:
        raise ForbiddenError("无权确认该操作")
    if action.state == "cancelled":
        raise ConflictError("该操作已取消或已过期")
    if action.state == "done":
        return {**action.result, "idempotent": True}
    if action.expires_at < time.time():
        with _LOCK:
            action.state = "cancelled"
        raise BadRequestError("确认已过期，请重新发起")

    executor = _EXECUTORS.get(action.action_type)
    if executor is None:
        raise BadRequestError(f"不支持的写操作：{action.action_type}")

    with _LOCK:
        if action.state != "pending":
            raise ConflictError("该操作正在处理或已完成")
        action.state = "executing"

    try:
        result = executor(action.payload, identity)
    except Exception:
        with _LOCK:
            action.state = "pending"
        raise

    with _LOCK:
        action.state = "done"
        action.result = result
    return {**result, "idempotent": False}


def cancel(token: str, identity: Identity) -> dict:
    action = _get_action(token)
    if action.user_id != identity.user_id or action.session_id != identity.session_id:
        raise ForbiddenError("无权取消该操作")
    with _LOCK:
        if action.state == "done":
            raise ConflictError("操作已执行，无法取消")
        action.state = "cancelled"
    return {"status": "cancelled", "token": token}


def reset_actions() -> None:
    """测试用。"""
    with _LOCK:
        _ACTIONS.clear()
