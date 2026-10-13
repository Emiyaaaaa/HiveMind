"""A redelivered job must preserve a completed or paused execution segment."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.events.bus import InMemoryEventBus
from app.models import Agent, Checkpoint, Message, Run, RunStatus, Step, ToolCall
from app.models.memory import MemoryItem
from app.models.quota import AgentQuotaUsage
from app.runtime.resume_context import resume_metadata
from app.schemas.run import RunCreate, RunResume, RunRetry
from app.services.run_service import RunService
from app.worker.cancel import InMemoryCancelRegistry
from app.worker.executor import RunExecutor
from app.worker.queue import InMemoryJobQueue, JobLease, RunJob
from app.worker.runner import _process_lease


@pytest_asyncio.fixture(autouse=True)
async def schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class RecordingQueue(InMemoryJobQueue):
    def __init__(self) -> None:
        super().__init__()
        self.acked: list[JobLease] = []
        self.fail_next_ack = False

    async def ack(self, lease: JobLease) -> None:
        if self.fail_next_ack:
            self.fail_next_ack = False
            raise ConnectionError("ACK connection lost")
        self.acked.append(lease)


async def make_run(
    bus: InMemoryEventBus,
    *,
    name: str,
    adapter: str = "echo",
    config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    async with SessionLocal() as session:
        agent = Agent(name=name, adapter=adapter, config=config or {"delay": 0})
        session.add(agent)
        await session.commit()
        run = await RunService(session=session, bus=bus).create_run(
            RunCreate(agent_id=agent.id, input={"prompt": "redelivery"})
        )
        return agent.id, run.id


def lease_for(agent_id: str, run_id: str, adapter: str) -> JobLease:
    return JobLease(
        job=RunJob.new(run_id=run_id, agent_id=agent_id, adapter=adapter),
        token="1700000000000-0",
        delivery_count=2,
    )


def row_data(row: Base) -> dict[str, Any]:
    return deepcopy({prop.key: getattr(row, prop.key) for prop in inspect(row).mapper.column_attrs})


async def snapshot(run_id: str, bus: InMemoryEventBus) -> dict[str, Any]:
    """Capture durable records and replay events, including cost and memory effects."""
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        captured: dict[str, Any] = {"run": row_data(run)}
        queries = {
            "steps": select(Step).where(Step.run_id == run_id).order_by(Step.id),
            "messages": select(Message).where(Message.run_id == run_id).order_by(Message.id),
            "tools": select(ToolCall).join(Step).where(Step.run_id == run_id).order_by(ToolCall.id),
            "checkpoints": select(Checkpoint)
            .where(Checkpoint.run_id == run_id)
            .order_by(Checkpoint.id),
            "memories": select(MemoryItem)
            .where(MemoryItem.source_run_id == run_id)
            .order_by(MemoryItem.id),
            "quota": select(AgentQuotaUsage)
            .where(AgentQuotaUsage.agent_id == run.agent_id)
            .order_by(AgentQuotaUsage.id),
        }
        for label, query in queries.items():
            captured[label] = [row_data(row) for row in await session.scalars(query)]
    captured["events"] = [
        (eid, deepcopy(event.model_dump())) async for eid, event in bus.replay(run_id)
    ]
    return captured


async def test_completed_run_redelivery_after_lost_ack_preserves_records():
    bus = InMemoryEventBus()
    agent_id, run_id = await make_run(
        bus,
        name="completed-redelivery",
        config={"delay": 0, "model": "openai/gpt-4o-mini", "quota": {"max_tokens": 1000}},
    )
    executor = RunExecutor(bus=bus, cancel_registry=InMemoryCancelRegistry())
    queue = RecordingQueue()
    lease = lease_for(agent_id, run_id, "echo")
    queue.fail_next_ack = True
    with pytest.raises(ConnectionError, match="ACK connection lost"):
        await _process_lease(executor, queue, lease)
    before = await snapshot(run_id, bus)
    assert before["run"]["status"] == RunStatus.SUCCEEDED
    assert before["tools"] and before["quota"] and before["memories"]

    await _process_lease(executor, queue, lease)

    assert await snapshot(run_id, bus) == before
    assert queue.acked == [lease]


async def test_waiting_run_redelivery_does_not_approve_or_execute_downstream_tool():
    bus = InMemoryEventBus()
    agent_id, run_id = await make_run(
        bus,
        name="waiting-redelivery",
        adapter="langgraph",
        config={
            "tools": ["echo"],
            "graph": {
                "nodes": [
                    {"id": "approval", "type": "human"},
                    {"id": "publish", "type": "tool", "tool": "echo"},
                ]
            },
        },
    )
    executor = RunExecutor(bus=bus, cancel_registry=InMemoryCancelRegistry())
    queue = RecordingQueue()
    lease = lease_for(agent_id, run_id, "langgraph")
    queue.fail_next_ack = True
    with pytest.raises(ConnectionError, match="ACK connection lost"):
        await _process_lease(executor, queue, lease)
    before = await snapshot(run_id, bus)
    assert before["run"]["status"] == RunStatus.WAITING_HUMAN
    assert before["tools"] == []

    await _process_lease(executor, queue, lease)

    assert await snapshot(run_id, bus) == before
    assert queue.acked == [lease]


@pytest.mark.parametrize("status", [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED])
async def test_terminal_run_ignores_stale_cancel_and_invalid_version_metadata(status):
    bus = InMemoryEventBus()
    agent_id, run_id = await make_run(bus, name="terminal-guard")
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        run.status = status
        run.output = {"preserved": True}
        run.error = "original outcome"
        run.metadata_ = {"_agentflow": {"agent_version": "invalid"}}
        await session.commit()
    registry = InMemoryCancelRegistry()
    await registry.request_cancel(run_id)
    before = await snapshot(run_id, bus)
    queue = RecordingQueue()
    executor = RunExecutor(bus=bus, cancel_registry=registry)
    lease = lease_for(agent_id, run_id, "echo")

    await _process_lease(executor, queue, lease)

    assert await snapshot(run_id, bus) == before
    assert queue.acked == [lease]


@pytest.mark.parametrize("mode", ["retry", "resume"])
async def test_explicit_api_request_executes_queued_run(monkeypatch, mode):
    monkeypatch.setattr(get_settings(), "worker_mode", "queue")
    config = (
        {"delay": 0, "fail_at_node": "tool"}
        if mode == "retry"
        else {
            "delay": 0,
            "pause_before_reply": True,
        }
    )
    bus = InMemoryEventBus()
    agent_id, run_id = await make_run(bus, name=f"explicit-{mode}", config=config)
    queue = RecordingQueue()
    registry = InMemoryCancelRegistry()
    executor = RunExecutor(bus=bus, cancel_registry=registry)
    await _process_lease(executor, queue, lease_for(agent_id, run_id, "echo"))

    async with SessionLocal() as session:
        service = RunService(session=session, bus=bus, job_queue=queue, cancel_registry=registry)
        if mode == "retry":
            pending = await service.retry_run(run_id, RunRetry())
        else:
            pending = await service.resume_run(run_id, RunResume(input={"approval": "approved"}))
        assert pending.status == RunStatus.PENDING
        assert pending.metadata_["_resume"]["mode"] == mode

    consumer = queue.consume()
    try:
        lease = await anext(consumer)
    finally:
        await consumer.aclose()
    await _process_lease(executor, queue, lease)

    after = await snapshot(run_id, bus)
    assert after["run"]["status"] == RunStatus.SUCCEEDED
    assert "_resume" not in after["run"]["metadata_"]
    assert after["run"]["output"]["reply"].startswith("echo: redelivery")
    assert len(queue.acked) == 2


async def make_paused_graph(bus: InMemoryEventBus, name: str) -> tuple[str, str]:
    agent_id, run_id = await make_run(
        bus,
        name=name,
        adapter="langgraph",
        config={
            "tools": ["echo"],
            "graph": {
                "nodes": [
                    {"id": "approval", "type": "human"},
                    {"id": "publish", "type": "tool", "tool": "echo"},
                ]
            },
        },
    )
    await RunExecutor(bus=bus).execute(run_id, "langgraph")
    return agent_id, run_id


async def test_waiting_run_accepts_explicit_resume_metadata():
    bus = InMemoryEventBus()
    agent_id, run_id = await make_paused_graph(bus, "persisted-resume")
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        run.metadata_ = resume_metadata(mode="resume", human_input={"route": "approved"})
        await session.commit()

    queue = RecordingQueue()
    await _process_lease(RunExecutor(bus=bus), queue, lease_for(agent_id, run_id, "langgraph"))

    after = await snapshot(run_id, bus)
    assert after["run"]["status"] == RunStatus.SUCCEEDED
    assert [step["node"] for step in sorted(after["steps"], key=lambda step: step["index"])] == [
        "approval",
        "publish",
    ]
    approval = next(step for step in after["steps"] if step["node"] == "approval")
    assert approval["output"]["human_input"] == {"route": "approved"}
    assert len(after["tools"]) == 1
    assert len(queue.acked) == 1


async def test_waiting_run_with_retry_metadata_remains_paused():
    bus = InMemoryEventBus()
    agent_id, run_id = await make_paused_graph(bus, "paused-with-retry")
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        run.metadata_ = resume_metadata(mode="retry")
        await session.commit()
    before = await snapshot(run_id, bus)
    queue = RecordingQueue()

    await _process_lease(RunExecutor(bus=bus), queue, lease_for(agent_id, run_id, "langgraph"))

    assert await snapshot(run_id, bus) == before
    assert len(queue.acked) == 1


async def test_cancel_signal_still_cancels_a_paused_run():
    bus = InMemoryEventBus()
    agent_id, run_id = await make_paused_graph(bus, "cancel-paused")
    registry = InMemoryCancelRegistry()
    await registry.request_cancel(run_id)
    queue = RecordingQueue()

    await _process_lease(
        RunExecutor(bus=bus, cancel_registry=registry),
        queue,
        lease_for(agent_id, run_id, "langgraph"),
    )

    after = await snapshot(run_id, bus)
    assert after["run"]["status"] == RunStatus.CANCELLED
    assert after["tools"] == []
    assert len(queue.acked) == 1
    assert not await registry.is_cancelled(run_id)


async def test_running_run_recovers_from_checkpoint_without_repeating_finished_step():
    bus = InMemoryEventBus()
    agent_id, run_id = await make_run(bus, name="crash-recovery")
    async with SessionLocal() as session:
        service = RunService(session=session, bus=bus)
        run = await session.get(Run, run_id)
        run.status = RunStatus.RUNNING
        await session.commit()
        await service._handle_event(run_id, "step.started", {"index": 0, "node": "plan"})
        await service._handle_event(run_id, "step.completed", {"index": 0, "node": "plan"})
        await service._handle_event(run_id, "checkpoint.created", {"state": {"next_step_index": 1}})
    queue = RecordingQueue()

    await _process_lease(RunExecutor(bus=bus), queue, lease_for(agent_id, run_id, "echo"))

    after = await snapshot(run_id, bus)
    assert after["run"]["status"] == RunStatus.SUCCEEDED
    assert sorted((step["index"], step["node"]) for step in after["steps"]) == [
        (0, "plan"),
        (1, "tool"),
        (2, "reply"),
    ]
    assert len(queue.acked) == 1


async def test_running_run_without_checkpoint_retries_from_start():
    bus = InMemoryEventBus()
    agent_id, run_id = await make_run(
        bus,
        name="crash-before-checkpoint",
        config={"delay": 0, "fail_at_node": "tool"},
    )
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        run.status = RunStatus.RUNNING
        await session.commit()
    queue = RecordingQueue()

    await _process_lease(RunExecutor(bus=bus), queue, lease_for(agent_id, run_id, "echo"))

    assert (await snapshot(run_id, bus))["run"]["status"] == RunStatus.SUCCEEDED
    assert len(queue.acked) == 1


async def test_running_recovery_at_human_checkpoint_does_not_invent_approval():
    bus = InMemoryEventBus()
    _, run_id = await make_paused_graph(bus, "crash-at-human")
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        run.status = RunStatus.RUNNING
        await session.commit()

    await RunExecutor(bus=bus).execute(run_id, "langgraph")

    after = await snapshot(run_id, bus)
    assert after["run"]["status"] == RunStatus.WAITING_HUMAN
    assert after["tools"] == []


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.WAITING_HUMAN,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ],
)
async def test_temporal_activity_redelivery_returns_persisted_status(monkeypatch, status):
    from app.worker.temporal import activities

    bus = InMemoryEventBus()
    agent_id, run_id = await make_paused_graph(bus, "temporal-paused")
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        run.status = status
        await session.commit()
    before = await snapshot(run_id, bus)
    monkeypatch.setattr(activities, "_executor", RunExecutor(bus=bus))
    monkeypatch.setattr(activities.activity, "heartbeat", lambda *_: None)

    result = await activities.execute_run_segment(
        RunJob.new(run_id=run_id, agent_id=agent_id, adapter="langgraph").to_dict()
    )

    assert result == {"status": str(status)}
    assert await snapshot(run_id, bus) == before


@pytest.mark.parametrize("status", [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED])
async def test_temporal_cancel_redelivery_preserves_terminal_status(monkeypatch, status):
    from app.worker.temporal import activities

    bus = InMemoryEventBus()
    _, run_id = await make_run(bus, name="temporal-terminal-cancel")
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        run.status = status
        await session.commit()
    before = await snapshot(run_id, bus)
    monkeypatch.setattr(activities, "_executor", RunExecutor(bus=bus))

    assert await activities.finalize_cancelled(run_id) == {"status": str(status)}
    assert await snapshot(run_id, bus) == before


async def test_reclaimed_redis_stream_lease_keeps_human_approval_pending(monkeypatch):
    from fakeredis.aioredis import FakeRedis

    from app.worker.queue import RedisStreamsJobQueue

    redis = FakeRedis(decode_responses=True)

    def stream_queue(consumer):
        return RedisStreamsJobQueue(
            redis_client=redis,
            stream_key="redelivery:runs",
            group="workers",
            consumer=consumer,
            block_ms=10,
            claim_idle_ms=0,
            max_deliveries=5,
            dlq_key="redelivery:dlq",
        )

    bus = InMemoryEventBus()
    agent_id, run_id = await make_run(
        bus,
        name="redis-paused",
        adapter="langgraph",
        config={"graph": {"nodes": [{"id": "approval", "type": "human"}]}},
    )
    executor = RunExecutor(bus=bus)
    first_queue = stream_queue("worker-1")
    second_queue = stream_queue("worker-2")
    first_consumer = first_queue.consume()
    second_consumer = second_queue.consume()
    original_ack = redis.xack
    fail_ack = True

    async def lost_ack(*args, **kwargs):
        nonlocal fail_ack
        if fail_ack:
            fail_ack = False
            raise ConnectionError("ACK connection lost")
        return await original_ack(*args, **kwargs)

    monkeypatch.setattr(redis, "xack", lost_ack)
    try:
        await first_queue.enqueue(RunJob.new(run_id=run_id, agent_id=agent_id, adapter="langgraph"))
        first_lease = await anext(first_consumer)
        with pytest.raises(ConnectionError, match="ACK connection lost"):
            await _process_lease(executor, first_queue, first_lease)
        assert (await redis.xpending("redelivery:runs", "workers"))["pending"] == 1
        before = await snapshot(run_id, bus)
        assert before["run"]["status"] == RunStatus.WAITING_HUMAN

        reclaimed = await anext(second_consumer)
        assert reclaimed.token == first_lease.token
        assert reclaimed.delivery_count == 2
        await _process_lease(executor, second_queue, reclaimed)

        assert (await redis.xpending("redelivery:runs", "workers"))["pending"] == 0
        assert await snapshot(run_id, bus) == before
    finally:
        await first_consumer.aclose()
        await second_consumer.aclose()
        await redis.aclose()
