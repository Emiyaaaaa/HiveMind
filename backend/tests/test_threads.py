"""M1 Thread short-memory acceptance tests."""

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
async def test_thread_cross_run_messages_and_seed(client, monkeypatch):
    """Two runs share a thread; the second AdapterContext gets prior turns."""
    captured: list[list[dict]] = []

    from ulid import ULID

    from app.adapters import register_adapter
    from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
    from app.models.run import RunStatus

    adapter_name = f"thread-capture-{ULID()}"

    class CaptureAdapter(OrchestratorAdapter):
        name = adapter_name

        async def run(self, ctx: AdapterContext) -> AdapterResult:
            captured.append(list(ctx.thread_messages))
            await ctx.emit_step_started(index=0, node="reply")
            prompt = str(ctx.input.get("prompt") or "")
            await ctx.emit_message(role="user", content=prompt, step_index=0)
            reply = f"echo: {prompt}"
            await ctx.emit_message(role="assistant", content=reply, step_index=0)
            await ctx.emit_step_completed(
                index=0, node="reply", output={"reply": reply}
            )
            return AdapterResult(status=RunStatus.SUCCEEDED, output={"reply": reply})

    register_adapter(adapter_name, CaptureAdapter())

    agent = await client.post(
        "/v1/agents",
        json={"name": "thread-bot", "adapter": adapter_name, "config": {}},
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]

    thread = await client.post(
        "/v1/threads",
        json={"agent_id": agent_id, "title": "chat"},
    )
    assert thread.status_code == 201, thread.text
    thread_id = thread.json()["id"]

    run1 = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent_id,
            "thread_id": thread_id,
            "input": {"prompt": "hello"},
        },
    )
    assert run1.status_code == 202, run1.text
    body1 = await _poll_until(client, run1.json()["id"], {"succeeded", "failed"})
    assert body1["status"] == "succeeded"
    assert body1["thread_id"] == thread_id
    assert captured[0] == []

    run2 = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent_id,
            "thread_id": thread_id,
            "input": {"prompt": "follow-up"},
        },
    )
    assert run2.status_code == 202, run2.text
    body2 = await _poll_until(client, run2.json()["id"], {"succeeded", "failed"})
    assert body2["status"] == "succeeded"
    assert len(captured) == 2
    roles = [(m["role"], m["content"]) for m in captured[1]]
    assert ("user", "hello") in roles
    assert ("assistant", "echo: hello") in roles

    msgs = await client.get(f"/v1/threads/{thread_id}/messages")
    assert msgs.status_code == 200
    contents = [m["content"] for m in msgs.json()["items"]]
    assert "hello" in contents
    assert "follow-up" in contents
    assert all("run_id" in m for m in msgs.json()["items"])

    # Without thread_id behavior stays unchanged (empty thread_messages).
    run3 = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "solo"}},
    )
    assert run3.status_code == 202
    body3 = await _poll_until(client, run3.json()["id"], {"succeeded", "failed"})
    assert body3["status"] == "succeeded"
    assert body3.get("thread_id") is None
    assert captured[2] == []


@pytest.mark.asyncio
async def test_thread_cross_tenant_404(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "AGENTFLOW_AUTH_API_KEYS",
        "admin-a:tenant-a:admin,admin-b:tenant-b:admin",
    )
    get_settings.cache_clear()

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            agent = await client.post(
                "/v1/agents",
                headers={"Authorization": "Bearer admin-a"},
                json={"name": "a-bot", "adapter": "echo", "config": {"delay": 0}},
            )
            assert agent.status_code == 201
            agent_id = agent.json()["id"]

            thread = await client.post(
                "/v1/threads",
                headers={"Authorization": "Bearer admin-a"},
                json={"agent_id": agent_id},
            )
            assert thread.status_code == 201
            thread_id = thread.json()["id"]

            other = await client.get(
                f"/v1/threads/{thread_id}",
                headers={"Authorization": "Bearer admin-b"},
            )
            assert other.status_code == 404

            other_msgs = await client.get(
                f"/v1/threads/{thread_id}/messages",
                headers={"Authorization": "Bearer admin-b"},
            )
            assert other_msgs.status_code == 404

            # Creating a run with another tenant's thread_id also 404s.
            agent_b = await client.post(
                "/v1/agents",
                headers={"Authorization": "Bearer admin-b"},
                json={"name": "b-bot", "adapter": "echo", "config": {"delay": 0}},
            )
            denied = await client.post(
                "/v1/runs",
                headers={"Authorization": "Bearer admin-b"},
                json={
                    "agent_id": agent_b.json()["id"],
                    "thread_id": thread_id,
                    "input": {"prompt": "x"},
                },
            )
            assert denied.status_code == 404

    get_settings.cache_clear()
    import os

    os.environ.pop("AGENTFLOW_AUTH_ENABLED", None)
    os.environ.pop("AGENTFLOW_AUTH_API_KEYS", None)


@pytest.mark.asyncio
async def test_missing_thread_on_create_run_404(client):
    agent = await client.post(
        "/v1/agents",
        json={"name": "no-thread-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = agent.json()["id"]
    resp = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent_id,
            "thread_id": "01INVALIDTHREADID00000000",
            "input": {"prompt": "x"},
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_thread_message_pagination(client):
    agent = await client.post(
        "/v1/agents",
        json={"name": "page-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = agent.json()["id"]
    thread = await client.post(
        "/v1/threads",
        json={"agent_id": agent_id, "title": "paged"},
    )
    thread_id = thread.json()["id"]

    for i in range(3):
        run = await client.post(
            "/v1/runs",
            json={
                "agent_id": agent_id,
                "thread_id": thread_id,
                "input": {"prompt": f"turn-{i}"},
            },
        )
        body = await _poll_until(client, run.json()["id"], {"succeeded", "failed"})
        assert body["status"] == "succeeded"

    first = await client.get(f"/v1/threads/{thread_id}/messages?limit=2")
    assert first.status_code == 200
    page1 = first.json()
    assert len(page1["items"]) == 2
    assert page1["has_more"] is True
    assert page1["next_cursor"]

    second = await client.get(
        f"/v1/threads/{thread_id}/messages",
        params={"limit": 2, "cursor": page1["next_cursor"]},
    )
    assert second.status_code == 200
    page2 = second.json()
    assert page2["items"]
    ids1 = {m["id"] for m in page1["items"]}
    ids2 = {m["id"] for m in page2["items"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_load_thread_window_skips_tool_and_prompt_echo():
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app.models import Agent, Message, Run, Thread
    from app.models.run import RunStatus
    from app.services.thread_service import ThreadService

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        agent = Agent(name="win-bot", adapter="echo", config={})
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        thread = Thread(tenant_id=agent.tenant_id, agent_id=agent.id, title="w")
        session.add(thread)
        await session.commit()
        await session.refresh(thread)

        run = Run(
            tenant_id=agent.tenant_id,
            agent_id=agent.id,
            thread_id=thread.id,
            adapter="echo",
            status=RunStatus.SUCCEEDED,
            input={"prompt": "hi"},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        session.add_all(
            [
                Message(
                    run_id=run.id,
                    index=0,
                    role="system",
                    content="sys",
                    extra={"kind": "prompt_echo"},
                ),
                Message(run_id=run.id, index=1, role="user", content="hello"),
                Message(
                    run_id=run.id,
                    index=2,
                    role="assistant",
                    content="",
                    extra={"tool_calls": [{"id": "c1", "name": "echo"}]},
                ),
                Message(
                    run_id=run.id,
                    index=3,
                    role="tool",
                    content='{"ok":true}',
                    tool_call_id="c1",
                ),
                Message(run_id=run.id, index=4, role="assistant", content="done"),
            ]
        )
        await session.commit()

        service = ThreadService(session)
        window = await service.load_thread_window(thread.id)
        assert window == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "done"},
        ]
