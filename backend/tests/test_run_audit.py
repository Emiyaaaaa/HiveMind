"""Cancel/resume audit trail tests."""

from __future__ import annotations

import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings


async def _poll_until(client, run_id: str, statuses: set[str], *, attempts: int = 80):
    body: dict = {}
    for _ in range(attempts):
        detail = await client.get(f"/v1/runs/{run_id}")
        body = detail.json()
        if body["status"] in statuses:
            return body
        await asyncio.sleep(0.05)
    return body


@pytest.mark.asyncio
async def test_cancel_writes_audit_event(client):
    create = await client.post(
        "/v1/agents",
        json={"name": "cancel-audit-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = create.json()["id"]
    run_response = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "done"}},
    )
    run_id = run_response.json()["id"]
    body = await _poll_until(client, run_id, {"succeeded", "failed", "cancelled"})
    assert body["status"] == "succeeded"

    # Cancel remains idempotent on terminal runs and still records who asked.
    cancel = await client.post(f"/v1/runs/{run_id}/cancel")
    assert cancel.status_code == 204, cancel.text

    audit = await client.get(f"/v1/runs/{run_id}/audit")
    assert audit.status_code == 200, audit.text
    events = audit.json()
    assert len(events) == 1
    assert events[0]["action"] == "cancel"
    assert events[0]["actor_subject"] == "anonymous"
    assert events[0]["actor_role"] == "admin"
    assert events[0]["run_id"] == run_id


@pytest.mark.asyncio
async def test_resume_writes_audit_event(client):
    create = await client.post(
        "/v1/agents",
        json={
            "name": "resume-audit-bot",
            "adapter": "echo",
            "config": {"delay": 0, "pause_before_reply": True},
        },
    )
    agent_id = create.json()["id"]
    run_response = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "hold"}},
    )
    run_id = run_response.json()["id"]
    body = await _poll_until(client, run_id, {"waiting_human"})
    assert body["status"] == "waiting_human"

    resume = await client.post(
        f"/v1/runs/{run_id}/resume",
        json={"input": {"approval": "ok"}},
    )
    assert resume.status_code == 202, resume.text

    audit = await client.get(f"/v1/runs/{run_id}/audit")
    assert audit.status_code == 200, audit.text
    events = audit.json()
    assert len(events) == 1
    assert events[0]["action"] == "resume"
    assert events[0]["actor_subject"] == "anonymous"
    assert events[0]["detail"]["input"] == {"approval": "ok"}
    assert "checkpoint_index" in events[0]["detail"]


@pytest.fixture
async def authed_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFLOW_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "AGENTFLOW_AUTH_API_KEYS",
        "admin-a:tenant-a:admin,ops-a:tenant-a:operator,viewer-a:tenant-a:viewer",
    )
    get_settings.cache_clear()

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        async with app.router.lifespan_context(app):
            yield ac

    get_settings.cache_clear()
    os.environ.pop("AGENTFLOW_AUTH_ENABLED", None)
    os.environ.pop("AGENTFLOW_AUTH_API_KEYS", None)


@pytest.mark.asyncio
async def test_cancel_audit_records_operator_subject(authed_client: AsyncClient):
    headers = {"Authorization": "Bearer ops-a"}
    create = await authed_client.post(
        "/v1/agents",
        headers={"Authorization": "Bearer admin-a"},
        json={"name": "ops-cancel-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    assert create.status_code == 201, create.text
    agent_id = create.json()["id"]

    run_response = await authed_client.post(
        "/v1/runs",
        headers=headers,
        json={"agent_id": agent_id, "input": {"prompt": "x"}},
    )
    assert run_response.status_code == 202, run_response.text
    run_id = run_response.json()["id"]

    for _ in range(80):
        detail = await authed_client.get(f"/v1/runs/{run_id}", headers=headers)
        if detail.json()["status"] in {"succeeded", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.05)

    cancel = await authed_client.post(f"/v1/runs/{run_id}/cancel", headers=headers)
    assert cancel.status_code == 204, cancel.text

    audit = await authed_client.get(
        f"/v1/runs/{run_id}/audit",
        headers={"Authorization": "Bearer viewer-a"},
    )
    assert audit.status_code == 200, audit.text
    events = audit.json()
    assert len(events) == 1
    assert events[0]["action"] == "cancel"
    assert events[0]["actor_subject"] == "ops-a"
    assert events[0]["actor_role"] == "operator"
