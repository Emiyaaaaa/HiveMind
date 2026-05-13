"""Worker + queue + cancel-registry contract tests.

Exercises the same execution path the Java API server drives in production:

1. API enqueues a ``RunJob`` instead of spawning an inline asyncio task.
2. ``RunExecutor`` pops the job, calls the adapter and writes terminal
   state via the shared ``RunService`` helpers.
3. ``CancelSignal`` set by the API short-circuits execution.

These tests use the in-memory queue and registry so they run without Redis
but exercise the exact code paths used in queue mode.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters import register_adapter
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.events import get_event_bus
from app.models import Agent, Run, RunStatus
from app.schemas.run import RunCreate
from app.services.run_service import RunService
from app.worker.cancel import InMemoryCancelRegistry
from app.worker.executor import RunExecutor
from app.worker.queue import InMemoryJobQueue, RunJob


@pytest.fixture(autouse=True)
async def schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
def queue_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "worker_mode", "queue", raising=False)
    yield


async def _make_agent(session, adapter: str = "echo") -> Agent:
    agent = Agent(name=f"agent-{id(session)}", adapter=adapter, config={"delay": 0})
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@pytest.mark.asyncio
async def test_start_run_enqueues_job_in_queue_mode(queue_mode):
    bus = get_event_bus()
    queue = InMemoryJobQueue()
    cancel_registry = InMemoryCancelRegistry()

    async with SessionLocal() as session:
        agent = await _make_agent(session)
        service = RunService(
            session=session,
            bus=bus,
            job_queue=queue,
            cancel_registry=cancel_registry,
        )
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={"prompt": "hi"})
        )
        await service.start_run(run.id)

    # The job should be on the queue; the run should still be PENDING since
    # no inline task ran.
    consumer = queue.consume()
    job: RunJob = await asyncio.wait_for(consumer.__anext__(), timeout=1.0)
    assert job.run_id == run.id
    assert job.adapter == "echo"

    async with SessionLocal() as session:
        loaded = await session.get(Run, run.id)
        assert loaded is not None
        assert loaded.status == RunStatus.PENDING


@pytest.mark.asyncio
async def test_executor_drives_run_to_succeeded():
    bus = get_event_bus()

    async with SessionLocal() as session:
        agent = await _make_agent(session)
        service = RunService(session=session, bus=bus)
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={"prompt": "hello"})
        )

    executor = RunExecutor(bus=bus, cancel_registry=InMemoryCancelRegistry())
    await executor.execute(run.id, "echo")

    async with SessionLocal() as session:
        loaded = await session.get(Run, run.id)
        assert loaded is not None
        assert loaded.status == RunStatus.SUCCEEDED
        assert loaded.output == {"reply": "echo: hello"}


class _SlowAdapter(OrchestratorAdapter):
    name = "slow"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        for i in range(50):
            await ctx.emit_step_started(index=i, node=f"step-{i}")
            await asyncio.sleep(0.05)
            await ctx.emit_step_completed(index=i, node=f"step-{i}")
        return AdapterResult(status=RunStatus.SUCCEEDED, output={})


@pytest.mark.asyncio
async def test_cancel_registry_aborts_execution():
    register_adapter("slow-test", _SlowAdapter())
    bus = get_event_bus()
    cancel_registry = InMemoryCancelRegistry()

    async with SessionLocal() as session:
        agent = Agent(name="slow-agent", adapter="slow-test", config={})
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        service = RunService(session=session, bus=bus, cancel_registry=cancel_registry)
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={"prompt": ""}, adapter="slow-test")
        )

    executor = RunExecutor(bus=bus, cancel_registry=cancel_registry)

    async def trip_cancel() -> None:
        await asyncio.sleep(0.1)
        await cancel_registry.request_cancel(run.id)

    cancel_task = asyncio.create_task(trip_cancel())
    try:
        await executor.execute(run.id, "slow-test")
    except asyncio.CancelledError:
        # Either the executor re-raises (inline path) or it absorbs and
        # finalises; both leave the run in CANCELLED state.
        pass
    await cancel_task

    async with SessionLocal() as session:
        loaded = await session.get(Run, run.id)
        assert loaded is not None
        assert loaded.status == RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_runjob_round_trip():
    job = RunJob.new(run_id="r1", agent_id="a1", adapter="echo")
    payload = job.to_json()
    restored = RunJob.from_json(payload)
    assert restored.run_id == "r1"
    assert restored.agent_id == "a1"
    assert restored.adapter == "echo"
    assert restored.enqueued_at == job.enqueued_at
