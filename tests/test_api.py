# -*- coding: utf-8 -*-
"""接口层测试：健康检查、统一错误体、静态页面、确认单接口。"""
from __future__ import annotations

import pytest

from backend.services import actions, after_sales
from backend.services.db import transaction
from backend.services.identity import Identity

SESSION = "api-test-session"
BUYER = Identity(user_id="u_buyer_001", role="buyer", session_id=SESSION)
HEADERS = {
    "X-User-Id": BUYER.user_id,
    "X-User-Role": BUYER.role,
    "X-Session-Id": SESSION,
}


def _clear_tickets() -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM tickets")


@pytest.fixture(autouse=True)
def clean_state():
    actions.reset_actions()
    _clear_tickets()
    yield
    actions.reset_actions()
    _clear_tickets()


def test_health_and_frontend(client):
    assert client.get("/healthz").json()["status"] == "ok"

    page = client.get("/")
    assert page.status_code == 200
    assert "ShopPilot" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_readyz_without_llm_key(client):
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["llm_key"] is False
    assert "DEEPSEEK_API_KEY" in body["hint"]


def test_meta_does_not_leak_secrets(client):
    body = client.get("/api/meta").json()
    assert body["llm_model"]
    assert "llm_key" not in body
    assert "DEEPSEEK_API_KEY" not in body
    assert "SILICONFLOW_API_KEY" not in body


def test_validation_error_uses_unified_body(client):
    response = client.post("/api/agent", json={"question": ""})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["request_id"]


def test_agent_returns_503_without_key(client):
    response = client.post(
        "/api/agent",
        json={"question": "你好", "session_id": SESSION},
        headers=HEADERS,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_agent_stream_emits_sse_events(client, monkeypatch):
    from backend.api import routes_agent

    async def fake_stream(question: str, identity):
        yield "tool", {"name": "search_products"}
        yield "token", {"text": "你好"}
        yield "done", {
            "answer": "你好",
            "tool_calls": ["search_products"],
            "sources": [],
            "cards": [],
            "truncated": False,
        }

    monkeypatch.setattr(routes_agent, "run_stream", fake_stream)
    monkeypatch.setattr(routes_agent, "_ensure_ready", lambda: None)

    response = client.post(
        "/api/agent/stream",
        json={"question": "你好", "session_id": SESSION},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: tool" in body
    assert "event: token" in body
    assert '"text": "你好"' in body
    assert "event: done" in body


def _issue_complaint_ticket() -> str:
    result = after_sales.request_ticket(
        BUYER, "SO20261001008", "complaint", "物流长时间停滞，需要人工跟进"
    )
    assert result["ok"] is True
    return result["pending_action"]["token"]


def test_action_cancel_then_confirm_conflicts(client):
    token = _issue_complaint_ticket()

    cancelled = client.post(f"/api/actions/{token}/cancel", headers=HEADERS)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    response = client.post(f"/api/actions/{token}/confirm", headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_action_confirm_is_idempotent(client):
    token = _issue_complaint_ticket()

    first = client.post(f"/api/actions/{token}/confirm", headers=HEADERS)
    assert first.status_code == 200
    ticket = first.json()
    assert ticket["ticket_id"].startswith("AS")
    assert ticket["idempotent"] is False

    second = client.post(f"/api/actions/{token}/confirm", headers=HEADERS)
    assert second.status_code == 200
    assert second.json()["ticket_id"] == ticket["ticket_id"]
    assert second.json()["idempotent"] is True


def test_action_confirm_requires_matching_session(client):
    token = _issue_complaint_ticket()
    headers = {**HEADERS, "X-Session-Id": "another-session"}

    response = client.post(f"/api/actions/{token}/confirm", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_action_confirm_requires_session_header(client):
    token = _issue_complaint_ticket()
    headers = {
        "X-User-Id": BUYER.user_id,
        "X-User-Role": BUYER.role,
    }

    response = client.post(f"/api/actions/{token}/confirm", headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
