"""M2 episodic summary: ingest on finish, inject on the next run, forget."""

from __future__ import annotations

import asyncio

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
async def test_episode_recalled_then_forgotten(client):
    captured: list[dict] = []

    from ulid import ULID

    from app.adapters import register_adapter
    from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
    from app.models.run import RunStatus

    adapter_name = f"episode-capture-{ULID()}"

    class CaptureAdapter(OrchestratorAdapter):
        name = adapter_name

        async def run(self, ctx: AdapterContext) -> AdapterResult:
            captured.append(
                {
                    "thread": list(ctx.thread_messages),
                    "hits": [hit.id for hit in ctx.memory_hits],
                }
            )
            await ctx.emit_step_started(index=0, node="reply")
            prompt = str(ctx.input.get("prompt") or "")
            await ctx.emit_message(role="user", content=prompt, step_index=0)
            reply = f"echo: {prompt}"
            await ctx.emit_message(role="assistant", content=reply, step_index=0)
            await ctx.emit_step_completed(index=0, node="reply", output={"reply": reply})
            return AdapterResult(status=RunStatus.SUCCEEDED, output={"reply": reply})

    register_adapter(adapter_name, CaptureAdapter())

    agent = await client.post(
        "/v1/agents",
        json={"name": "episode-bot", "adapter": adapter_name, "config": {}},
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]
    thread = await client.post("/v1/threads", json={"agent_id": agent_id, "title": "plan"})
    assert thread.status_code == 201, thread.text
    thread_id = thread.json()["id"]

    run1 = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent_id,
            "thread_id": thread_id,
            "input": {"prompt": "批准方案 ALPHA-42"},
        },
    )
    assert run1.status_code == 202, run1.text
    body1 = await _poll_until(client, run1.json()["id"], {"succeeded", "failed"})
    assert body1["status"] == "succeeded"
    assert captured[0]["hits"] == []

    listed = await client.get("/v1/memories", params={"thread_id": thread_id, "q": "ALPHA-42"})
    assert listed.status_code == 200, listed.text
    episodes = listed.json()
    assert len(episodes) == 1
    assert episodes[0]["kind"] == "episode"
    assert episodes[0]["scope"] == "thread"
    assert "ALPHA-42" in episodes[0]["content"]
    assert episodes[0]["metadata"]["outcome"] == "succeeded"
    episode_id = episodes[0]["id"]

    run2 = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "thread_id": thread_id, "input": {"prompt": "继续"}},
    )
    assert run2.status_code == 202, run2.text
    body2 = await _poll_until(client, run2.json()["id"], {"succeeded", "failed"})
    assert body2["status"] == "succeeded"
    assert captured[1]["hits"] == [episode_id]
    seeded = captured[1]["thread"][0]
    assert seeded["role"] == "system"
    assert "ALPHA-42" in seeded["content"]

    messages = await client.get(f"/v1/runs/{run2.json()['id']}/messages")
    assert messages.status_code == 200, messages.text
    memory_rows = [m for m in messages.json()["items"] if m["extra"].get("kind") == "memory"]
    assert memory_rows
    assert memory_rows[0]["extra"]["memory_hit_ids"] == [episode_id]

    forgotten = await client.delete(f"/v1/memories/{episode_id}")
    assert forgotten.status_code == 204
    again = await client.get("/v1/memories", params={"q": "ALPHA-42", "thread_id": thread_id})
    assert again.status_code == 200
    assert all(row["id"] != episode_id for row in again.json())
    assert all("ALPHA-42" not in row["content"] for row in again.json())


@pytest.mark.asyncio
async def test_memory_search_is_tenant_scoped(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "AGENTFLOW_AUTH_API_KEYS",
        "admin-a:tenant-a:admin,admin-b:tenant-b:admin",
    )
    get_settings.cache_clear()

    from app.main import app

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with app.router.lifespan_context(app):
                created = await client.post(
                    "/v1/memories",
                    headers={"Authorization": "Bearer admin-a"},
                    json={
                        "content": "FACT-BLUE-77",
                        "kind": "fact",
                        "scope": "agent",
                        "agent_id": "agent-a",
                    },
                )
                assert created.status_code == 201, created.text
                memory_id = created.json()["id"]

                other = await client.get(
                    "/v1/memories",
                    headers={"Authorization": "Bearer admin-b"},
                    params={"q": "FACT-BLUE-77"},
                )
                assert other.status_code == 200
                assert other.json() == []

                denied = await client.delete(
                    f"/v1/memories/{memory_id}",
                    headers={"Authorization": "Bearer admin-b"},
                )
                assert denied.status_code == 404

                removed = await client.delete(
                    f"/v1/memories/{memory_id}",
                    headers={"Authorization": "Bearer admin-a"},
                )
                assert removed.status_code == 204
                gone = await client.get(
                    "/v1/memories",
                    headers={"Authorization": "Bearer admin-a"},
                    params={"q": "FACT-BLUE-77"},
                )
                assert gone.json() == []
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
