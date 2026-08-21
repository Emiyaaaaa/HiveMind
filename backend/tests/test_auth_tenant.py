"""Multi-tenant isolation and role checks (API key auth)."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings


@pytest.fixture
async def authed_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFLOW_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "AGENTFLOW_AUTH_API_KEYS",
        "admin-a:tenant-a:admin,viewer-a:tenant-a:viewer,"
        "admin-b:tenant-b:admin,ops-a:tenant-a:operator",
    )
    get_settings.cache_clear()

    # Re-import app after settings change so Depends(get_settings) sees new values.
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        async with app.router.lifespan_context(app):
            yield ac

    get_settings.cache_clear()
    os.environ.pop("AGENTFLOW_AUTH_ENABLED", None)
    os.environ.pop("AGENTFLOW_AUTH_API_KEYS", None)


@pytest.mark.asyncio
async def test_missing_key_returns_401(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/v1/agents")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_stays_open(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_create_agent(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/v1/agents",
        headers={"Authorization": "Bearer viewer-a"},
        json={"name": "blocked", "adapter": "echo"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tenant_isolation(authed_client: AsyncClient) -> None:
    created = await authed_client.post(
        "/v1/agents",
        headers={"X-Api-Key": "admin-a"},
        json={"name": "writer", "adapter": "echo"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["tenant_id"] == "tenant-a"
    agent_id = body["id"]

    other = await authed_client.get(
        f"/v1/agents/{agent_id}",
        headers={"Authorization": "Bearer admin-b"},
    )
    assert other.status_code == 404

    same = await authed_client.get(
        f"/v1/agents/{agent_id}",
        headers={"Authorization": "Bearer viewer-a"},
    )
    assert same.status_code == 200
    assert same.json()["id"] == agent_id


@pytest.mark.asyncio
async def test_operator_can_create_run(authed_client: AsyncClient) -> None:
    agent = await authed_client.post(
        "/v1/agents",
        headers={"Authorization": "Bearer admin-a"},
        json={"name": "runner", "adapter": "echo"},
    )
    assert agent.status_code == 201
    agent_id = agent.json()["id"]

    denied = await authed_client.post(
        "/v1/runs",
        headers={"Authorization": "Bearer viewer-a"},
        json={"agent_id": agent_id, "input": {"prompt": "hi"}},
    )
    assert denied.status_code == 403

    run = await authed_client.post(
        "/v1/runs",
        headers={"Authorization": "Bearer ops-a"},
        json={"agent_id": agent_id, "input": {"prompt": "hi"}},
    )
    assert run.status_code == 202
    assert run.json()["tenant_id"] == "tenant-a"
