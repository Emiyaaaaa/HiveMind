"""Message ↔ step association and tenant data retention tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.events import get_event_bus
from app.models import Checkpoint, Message, Run, RunStatus
from app.services.retention_service import RetentionService
from app.services.run_service import RunService


async def _complete_echo_run(client, agent_id: str, prompt: str = "hi") -> str:
    run_response = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": prompt}},
    )
    assert run_response.status_code == 202, run_response.text
    run_id = run_response.json()["id"]

    for _ in range(50):
        detail = await client.get(f"/v1/runs/{run_id}")
        body = detail.json()
        if body["status"] in {"succeeded", "failed", "cancelled"}:
            return run_id
        await asyncio.sleep(0.05)

    raise AssertionError(f"run {run_id} did not finish")


@pytest.mark.asyncio
async def test_messages_linked_to_steps(client):
    create = await client.post(
        "/v1/agents",
        json={"name": "step-link-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = create.json()["id"]
    run_id = await _complete_echo_run(client, agent_id)

    detail = await client.get(f"/v1/runs/{run_id}")
    body = detail.json()
    steps_by_node = {step["node"]: step for step in body["steps"]}
    messages = body["messages"]

    user_msg = next(m for m in messages if m["role"] == "user")
    assistant_msg = next(m for m in messages if m["role"] == "assistant")

    assert user_msg["step_id"] == steps_by_node["plan"]["id"]
    assert assistant_msg["step_id"] == steps_by_node["reply"]["id"]


@pytest.mark.asyncio
async def test_erase_run_data_removes_messages_and_checkpoints(client):
    create = await client.post(
        "/v1/agents",
        json={"name": "erase-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = create.json()["id"]
    run_id = await _complete_echo_run(client, agent_id)

    erase = await client.post(f"/v1/runs/{run_id}/erase")
    assert erase.status_code == 200, erase.text
    payload = erase.json()
    assert payload["messages_deleted"] >= 2
    assert payload["checkpoints_deleted"] >= 1

    detail = await client.get(f"/v1/runs/{run_id}")
    body = detail.json()
    assert body["messages"] == []
    assert body["checkpoints"] == []
    assert body["output"] is None
    assert len(body["steps"]) == 3


@pytest.mark.asyncio
async def test_erase_run_conflict_while_running():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    bus = get_event_bus()
    async with SessionLocal() as session:
        service = RetentionService(session=session, bus=bus)
        run = Run(
            tenant_id="default",
            agent_id="01AGENT",
            adapter="echo",
            status=RunStatus.RUNNING,
        )
        session.add(run)
        await session.commit()

        with pytest.raises(Exception) as exc:
            await service.erase_run_data(run.id, tenant_id="default")
        assert "Cannot erase" in str(exc.value)


@pytest.mark.asyncio
async def test_tenant_ttl_purge():
    from app.core.config import Settings

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    bus = get_event_bus()
    settings = Settings(data_retention_tenant_ttl_days=30)
    async with SessionLocal() as session:
        service = RetentionService(session=session, bus=bus, settings=settings)
        old_run = Run(
            tenant_id="default",
            agent_id="01AGENT",
            adapter="echo",
            status=RunStatus.SUCCEEDED,
            output={"reply": "old"},
            created_at=datetime.now(UTC) - timedelta(days=40),
        )
        session.add(old_run)
        await session.flush()
        session.add(
            Message(
                run_id=old_run.id,
                index=0,
                role="user",
                content="secret",
            )
        )
        session.add(
            Checkpoint(
                run_id=old_run.id,
                index=0,
                label="cp",
                state={"graph_state": {"reply": "old"}},
            )
        )
        await session.commit()

        result = await service.purge_expired(tenant_id="default")
        assert result["runs_purged"] == 1
        assert result["messages_deleted"] == 1
        assert result["checkpoints_deleted"] == 1

        refreshed = await session.get(Run, old_run.id)
        assert refreshed is not None
        assert refreshed.output is None

        remaining = await session.execute(
            select(Message).where(Message.run_id == old_run.id)
        )
        assert list(remaining.scalars().all()) == []


@pytest.mark.asyncio
async def test_run_service_resolves_step_index_to_step_id():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    bus = get_event_bus()
    async with SessionLocal() as session:
        run_service = RunService(session=session, bus=bus)
        run = Run(
            tenant_id="default",
            agent_id="01AGENT",
            adapter="echo",
            status=RunStatus.RUNNING,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        await run_service._handle_event(
            run.id,
            "step.started",
            {"index": 0, "node": "plan"},
        )
        await run_service._handle_event(
            run.id,
            "message.created",
            {
                "role": "user",
                "content": "hello",
                "step_index": 0,
                "extra": {},
            },
        )

        result = await session.execute(
            select(Message).where(Message.run_id == run.id)
        )
        message = result.scalar_one()
        step = await run_service._find_step(run.id, 0)
        assert step is not None
        assert message.step_id == step.id
