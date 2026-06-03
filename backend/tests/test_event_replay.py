"""Tests for SSE event replay via Last-Event-ID."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import fakeredis.aioredis as fakeredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.events.bus import InMemoryEventBus, RedisEventBus
from app.schemas.run import RunEvent


def _event(event_type: str, run_id: str, **data: object) -> RunEvent:
    return RunEvent(
        type=event_type,
        run_id=run_id,
        at=datetime.now(UTC),
        data=dict(data),
    )


async def _collect_sse(
    client: AsyncClient,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    max_frames: int = 20,
) -> list[dict[str, str | None]]:
    frames: list[dict[str, str | None]] = []
    async with client.stream(
        "GET",
        path,
        headers=headers or {},
        timeout=5.0,
    ) as response:
        assert response.status_code == 200
        event_name: str | None = None
        event_id: str | None = None
        data_lines: list[str] = []

        async for line in response.aiter_lines():
            if line == "":
                if event_name is not None or data_lines:
                    frames.append(
                        {
                            "id": event_id,
                            "event": event_name,
                            "data": "\n".join(data_lines) if data_lines else None,
                        }
                    )
                event_name = None
                event_id = None
                data_lines = []
                if len(frames) >= max_frames:
                    break
                continue

            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                event_id = line[3:].strip()
            elif line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

    return frames


@pytest.mark.asyncio
async def test_sse_replay_after_last_event_id(monkeypatch):
    import app.events.bus as bus_module

    bus = InMemoryEventBus()
    monkeypatch.setattr(bus_module, "_bus", bus)

    from app.main import app

    run_id = "run-replay-1"
    await bus.publish(_event("run.created", run_id))
    await bus.publish(_event("run.started", run_id))
    await bus.publish(_event("step.started", run_id, index=0, node="plan"))
    await bus.publish(_event("step.completed", run_id, index=0))
    await bus.publish(_event("run.completed", run_id, output={"reply": "ok"}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            replay = await _collect_sse(
                client,
                f"/v1/events/{run_id}",
                headers={"Last-Event-ID": "1"},
                max_frames=10,
            )

    event_names = [frame["event"] for frame in replay if frame["event"] != "ping"]
    assert event_names == [
        "run.started",
        "step.started",
        "step.completed",
        "run.completed",
    ]
    assert all(frame["id"] for frame in replay if frame["event"] != "ping")


@pytest.mark.asyncio
async def test_sse_replay_query_param(monkeypatch):
    import app.events.bus as bus_module

    bus = InMemoryEventBus()
    monkeypatch.setattr(bus_module, "_bus", bus)

    from app.main import app

    run_id = "run-replay-2"
    await bus.publish(_event("run.created", run_id))
    await bus.publish(_event("run.started", run_id))
    await bus.publish(_event("run.completed", run_id, output={}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            second = await _collect_sse(
                client,
                f"/v1/events/{run_id}?last_event_id=1",
                max_frames=5,
            )

    event_names = [frame["event"] for frame in second if frame["event"] != "ping"]
    assert event_names == ["run.started", "run.completed"]


@pytest.mark.asyncio
async def test_sse_live_stream_includes_event_ids(monkeypatch):
    import app.events.bus as bus_module

    bus = InMemoryEventBus()
    monkeypatch.setattr(bus_module, "_bus", bus)

    from app.main import app

    run_id = "run-live-ids"

    async def publish_run() -> None:
        await asyncio.sleep(0.05)
        await bus.publish(_event("run.created", run_id))
        await bus.publish(_event("run.completed", run_id, output={}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            publisher = asyncio.create_task(publish_run())
            frames = await _collect_sse(
                client,
                f"/v1/events/{run_id}",
                max_frames=5,
            )
            await publisher

    ids = [frame["id"] for frame in frames if frame["event"] != "ping"]
    assert ids == ["1", "2"]


@pytest.mark.asyncio
async def test_redis_event_bus_replay_with_fakeredis():
    redis = fakeredis.FakeRedis(decode_responses=True)
    bus = RedisEventBus.__new__(RedisEventBus)
    bus._redis = redis
    bus._channel_prefix = "agentflow:run:"
    bus._stream_suffix = ":log"
    bus._stream_max_len = 1000

    run_id = "run-redis-1"
    id1 = await bus.publish(_event("run.created", run_id))
    id2 = await bus.publish(_event("run.started", run_id))
    await bus.publish(_event("run.completed", run_id, output={}))

    replayed = [event_id async for event_id, _ in bus.replay(run_id, id1)]
    assert replayed == [id2]
    assert id1 != id2

    full = [event.type async for _, event in bus.replay(run_id, None)]
    assert full == ["run.created", "run.started", "run.completed"]
