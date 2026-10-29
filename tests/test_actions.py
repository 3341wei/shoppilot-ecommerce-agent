# -*- coding: utf-8 -*-
"""确认单机制：归属、TTL、幂等、取消。"""
from __future__ import annotations

import time

import pytest

from backend.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from backend.services import actions
from backend.services.identity import Identity

BUYER = Identity(user_id="u_buyer_001", role="buyer", session_id="s_1")
OTHER_USER = Identity(user_id="u_buyer_002", role="buyer", session_id="s_1")
OTHER_SESSION = Identity(user_id="u_buyer_001", role="buyer", session_id="s_2")

_executed: list[dict] = []


def _executor(payload: dict, identity: Identity) -> dict:
    _executed.append({"payload": payload, "user_id": identity.user_id})
    return {"status": "created", "ticket_id": "AS-TEST-001"}


@pytest.fixture(autouse=True)
def clean_state():
    actions.reset_actions()
    _executed.clear()
    actions.register_executor("test_action", _executor)
    yield
    actions.reset_actions()


def test_confirm_executes_once_and_is_idempotent():
    pending = actions.issue(BUYER, "test_action", "测试写操作", {"value": 1})
    assert pending["ttl_seconds"] == 300

    first = actions.confirm(pending["token"], BUYER)
    assert first["ticket_id"] == "AS-TEST-001"
    assert first["idempotent"] is False
    assert len(_executed) == 1

    second = actions.confirm(pending["token"], BUYER)
    assert second["ticket_id"] == "AS-TEST-001"
    assert second["idempotent"] is True
    assert len(_executed) == 1


def test_confirm_rejects_other_user_and_session():
    token = actions.issue(BUYER, "test_action", "测试写操作", {})["token"]

    with pytest.raises(ForbiddenError):
        actions.confirm(token, OTHER_USER)
    with pytest.raises(ForbiddenError):
        actions.confirm(token, OTHER_SESSION)
    assert _executed == []


def test_cancel_prevents_execution():
    token = actions.issue(BUYER, "test_action", "测试写操作", {})["token"]
    assert actions.cancel(token, BUYER)["status"] == "cancelled"

    with pytest.raises(ConflictError):
        actions.confirm(token, BUYER)
    assert _executed == []


def test_expired_action_is_rejected():
    token = actions.issue(BUYER, "test_action", "测试写操作", {})["token"]
    # 直接把过期时间拨到过去，避免测试等待
    actions._ACTIONS[token].expires_at = time.time() - 1

    with pytest.raises(BadRequestError):
        actions.confirm(token, BUYER)
    assert _executed == []


def test_unknown_token_and_action_type():
    with pytest.raises(NotFoundError):
        actions.confirm("not-a-real-token", BUYER)
    with pytest.raises(BadRequestError):
        actions.issue(BUYER, "unknown_action", "未知操作", {})
