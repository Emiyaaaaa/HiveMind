"""Batch and scheduled Run API tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.db.session import SessionLocal
from app.events import get_event_bus
from app.models import Run, RunSchedule
from app.services.agent_versions import INTERNAL_METADATA_KEY
from app.services.schedule_service import ScheduleService


async def _poll_terminal(client, run_id: str) -> dict:
    body: dict = {}
    for _ in range(80):
        detail = await client.get(f"/v1/runs/{run_id}")
        body = detail.json()
        if body["status"] in {"succeeded", "failed", "cancelled"}:
            return body
        await asyncio.sleep(0.05)
    return body


@pytest.mark.asyncio
async def test_batch_creates_multiple_runs(client):
    agent = await client.post(
        "/v1/agents",
        json={"name": "batch-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]

    batch = await client.post(
        "/v1/batches",
        json={
            "agent_id": agent_id,
            "items": [
                {"input": {"prompt": "one"}},
                {"input": {"prompt": "two"}},
            ],
        },
    )
    assert batch.status_code == 202, batch.text
    body = batch.json()
    assert body["total"] == 2
    assert len(body["run_ids"]) == 2
    assert body["status"] in {"pending", "running", "completed"}

    detail = await client.get(f"/v1/batches/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["run_ids"] == body["run_ids"]

    runs = await client.get(f"/v1/batches/{body['id']}/runs")
    assert runs.status_code == 200
    assert len(runs.json()) == 2

    for run_id in body["run_ids"]:
        got = await _poll_terminal(client, run_id)
        assert got["status"] == "succeeded"
        async with SessionLocal() as session:
            row = await session.get(Run, run_id)
            assert row is not None
            assert row.metadata_[INTERNAL_METADATA_KEY]["batch_id"] == body["id"]


@pytest.mark.asyncio
async def test_batch_rejects_empty_items(client):
    agent = await client.post(
        "/v1/agents",
        json={"name": "batch-empty", "adapter": "echo", "config": {}},
    )
    agent_id = agent.json()["id"]
    resp = await client.post(
        "/v1/batches",
        json={"agent_id": agent_id, "items": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_schedule_interval_trigger_and_patch(client):
    agent = await client.post(
        "/v1/agents",
        json={"name": "sched-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = agent.json()["id"]

    created = await client.post(
        "/v1/schedules",
        json={
            "agent_id": agent_id,
            "name": "every-minute",
            "interval_seconds": 60,
            "input": {"prompt": "tick"},
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    schedule = created.json()
    assert schedule["interval_seconds"] == 60
    assert schedule["cron"] is None
    assert schedule["enabled"] is True

    triggered = await client.post(f"/v1/schedules/{schedule['id']}/trigger")
    assert triggered.status_code == 202, triggered.text
    run_id = triggered.json()["id"]
    async with SessionLocal() as session:
        row = await session.get(Run, run_id)
        assert row is not None
        assert row.metadata_[INTERNAL_METADATA_KEY]["schedule_id"] == schedule["id"]

    body = await _poll_terminal(client, run_id)
    assert body["status"] == "succeeded"

    runs = await client.get(f"/v1/schedules/{schedule['id']}/runs")
    assert runs.status_code == 200
    assert any(item["id"] == run_id for item in runs.json())

    patched = await client.patch(
        f"/v1/schedules/{schedule['id']}",
        json={"enabled": False, "name": "paused"},
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["name"] == "paused"

    deleted = await client.delete(f"/v1/schedules/{schedule['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/v1/schedules/{schedule['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_schedule_cron_validation(client):
    agent = await client.post(
        "/v1/agents",
        json={"name": "cron-bot", "adapter": "echo", "config": {}},
    )
    agent_id = agent.json()["id"]

    bad = await client.post(
        "/v1/schedules",
        json={
            "agent_id": agent_id,
            "cron": "not a cron",
            "input": {"prompt": "x"},
        },
    )
    assert bad.status_code == 422

    both = await client.post(
        "/v1/schedules",
        json={
            "agent_id": agent_id,
            "cron": "0 * * * *",
            "interval_seconds": 60,
            "input": {"prompt": "x"},
        },
    )
    assert both.status_code == 422

    ok = await client.post(
        "/v1/schedules",
        json={
            "agent_id": agent_id,
            "cron": "0 * * * *",
            "timezone": "UTC",
            "input": {"prompt": "hourly"},
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["cron"] == "0 * * * *"


@pytest.mark.asyncio
async def test_schedule_sweeper_fires_due_row(client):
    agent = await client.post(
        "/v1/agents",
        json={"name": "due-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = agent.json()["id"]

    created = await client.post(
        "/v1/schedules",
        json={
            "agent_id": agent_id,
            "interval_seconds": 60,
            "input": {"prompt": "due"},
            "enabled": True,
        },
    )
    schedule_id = created.json()["id"]

    async with SessionLocal() as session:
        row = await session.get(RunSchedule, schedule_id)
        assert row is not None
        row.next_run_at = datetime.now(UTC) - timedelta(seconds=5)
        await session.commit()

    async with SessionLocal() as session:
        service = ScheduleService(session=session, bus=get_event_bus())
        result = await service.fire_due_schedules(limit=10)
    assert result["schedules_fired"] >= 1

    async with SessionLocal() as session:
        row = await session.get(RunSchedule, schedule_id)
        assert row is not None
        assert row.last_run_id is not None
        next_at = row.next_run_at
        if next_at.tzinfo is None:
            next_at = next_at.replace(tzinfo=UTC)
        assert next_at > datetime.now(UTC) - timedelta(seconds=1)

    runs = await client.get(f"/v1/schedules/{schedule_id}/runs")
    assert runs.status_code == 200
    assert len(runs.json()) >= 1
