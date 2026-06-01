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
from sqlalchemy import select

from app.adapters import register_adapter
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.events import get_event_bus
from app.models import Agent, Run, RunStatus, Step
from app.schemas.run import RunCreate
from app.services.run_service import RunService
from app.worker.cancel import InMemoryCancelRegistry
from app.worker.executor import RunExecutor
from app.worker.queue import InMemoryJobQueue, JobLease, RunJob


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
    lease: JobLease = await asyncio.wait_for(consumer.__anext__(), timeout=1.0)
    assert lease.job.run_id == run.id
    assert lease.job.adapter == "echo"
    assert lease.token is None  # in-memory queue has no ACK token

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


@pytest.mark.asyncio
async def test_step_completed_preserves_existing_metrics_when_missing_from_event():
    bus = get_event_bus()

    async with SessionLocal() as session:
        agent = await _make_agent(session)
        service = RunService(session=session, bus=bus)
        run = await service.create_run(RunCreate(agent_id=agent.id, input={"prompt": "x"}))

        await service._handle_event(run.id, "step.started", {"index": 0, "node": "n0"})

        step = await service._find_step(run.id, 0)
        assert step is not None
        step.latency_ms = 123
        step.tokens_in = 4
        step.tokens_out = 9
        await session.commit()

        await service._handle_event(run.id, "step.completed", {"index": 0, "output": {"ok": True}})

    async with SessionLocal() as session:
        step = (
            await session.execute(
                select(Step).where(Step.run_id == run.id, Step.index == 0)
            )
        ).scalar_one()
        assert step.status == RunStatus.SUCCEEDED
        assert step.output == {"ok": True}
        assert step.latency_ms == 123
        assert step.tokens_in == 4
        assert step.tokens_out == 9


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


# Runner ACK semantics ---------------------------------------------------------


class _RecordingQueue:
    """Minimal ``JobQueue`` that records ACK calls; consume/enqueue unused."""

    def __init__(self) -> None:
        self.acked: list[JobLease] = []

    async def enqueue(self, job: RunJob) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    async def consume(self):  # pragma: no cover - unused
        if False:
            yield  # type: ignore[unreachable]

    async def ack(self, lease: JobLease) -> None:
        self.acked.append(lease)

    async def aclose(self) -> None:  # pragma: no cover - unused
        return None


class _BoomAdapter(OrchestratorAdapter):
    name = "boom"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        raise RuntimeError("kaboom")


@pytest.mark.asyncio
async def test_runner_acks_after_successful_execute():
    from app.worker.runner import _process_lease

    bus = get_event_bus()
    queue = _RecordingQueue()

    async with SessionLocal() as session:
        agent = await _make_agent(session)
        service = RunService(session=session, bus=bus)
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={"prompt": "hi"})
        )

    executor = RunExecutor(bus=bus, cancel_registry=InMemoryCancelRegistry())
    lease = JobLease(
        job=RunJob.new(run_id=run.id, agent_id=run.agent_id, adapter="echo"),
        token="1700000000000-0",
    )
    await _process_lease(executor, queue, lease)

    assert [acked.token for acked in queue.acked] == ["1700000000000-0"]


@pytest.mark.asyncio
async def test_runner_acks_when_adapter_records_failure():
    """Adapter exceptions are captured by RunExecutor as RunStatus.FAILED.

    Execute() returns normally in that case, so the runner MUST ACK -- the
    DB row is already in a terminal state and replaying would race with it.
    """
    from app.worker.runner import _process_lease

    register_adapter("boom-test", _BoomAdapter())
    bus = get_event_bus()
    queue = _RecordingQueue()

    async with SessionLocal() as session:
        agent = Agent(name="boom-agent", adapter="boom-test", config={})
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        service = RunService(session=session, bus=bus)
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={}, adapter="boom-test")
        )

    executor = RunExecutor(bus=bus, cancel_registry=InMemoryCancelRegistry())
    lease = JobLease(
        job=RunJob.new(run_id=run.id, agent_id=run.agent_id, adapter="boom-test"),
        token="1700000000001-0",
    )
    await _process_lease(executor, queue, lease)

    assert [acked.token for acked in queue.acked] == ["1700000000001-0"]

    async with SessionLocal() as session:
        loaded = await session.get(Run, run.id)
        assert loaded is not None
        assert loaded.status == RunStatus.FAILED


@pytest.mark.asyncio
async def test_runner_does_not_ack_on_infrastructure_error(monkeypatch):
    """If ``execute`` itself raises (not the adapter), the lease must stay
    pending so XAUTOCLAIM can redeliver it to another worker."""
    from app.worker import runner as runner_module

    queue = _RecordingQueue()

    class _BrokenExecutor:
        async def execute(self, run_id: str, adapter: str) -> None:
            raise RuntimeError("redis went away")

    lease = JobLease(
        job=RunJob.new(run_id="r-x", agent_id="a-x", adapter="echo"),
        token="1700000000002-0",
    )
    await runner_module._process_lease(_BrokenExecutor(), queue, lease)  # type: ignore[arg-type]

    assert queue.acked == []


def _leases_for_runs(run_ids: list[str], agent_id: str) -> list[JobLease]:
    return [
        JobLease(
            job=RunJob.new(run_id=run_id, agent_id=agent_id, adapter="echo"),
            token=f"entry-{index}",
        )
        for index, run_id in enumerate(run_ids)
    ]


class _FiniteQueue:
    """Yields a fixed list of leases then ends, for consume-loop tests."""

    def __init__(self, leases: list[JobLease]) -> None:
        self._leases = leases
        self.acked: list[JobLease] = []

    async def ack(self, lease: JobLease) -> None:
        self.acked.append(lease)

    async def aclose(self) -> None:  # pragma: no cover - unused
        return None

    async def consume(self):
        for lease in self._leases:
            yield lease


@pytest.mark.asyncio
async def test_consume_loop_respects_worker_concurrency():
    from app.worker import runner as runner_module

    active = [0]
    hold = asyncio.Event()

    class _BlockingExecutor:
        async def execute(self, run_id: str, adapter: str) -> None:
            active[0] += 1
            try:
                await hold.wait()
            finally:
                active[0] -= 1

    queue = _FiniteQueue(_leases_for_runs(["r1", "r2", "r3"], "agent-1"))
    stop = asyncio.Event()

    loop_task = asyncio.create_task(
        runner_module._consume_loop(
            executor=_BlockingExecutor(),  # type: ignore[arg-type]
            queue=queue,  # type: ignore[arg-type]
            stop=stop,
            concurrency=2,
        )
    )

    for _ in range(50):
        await asyncio.sleep(0.01)
        if active[0] >= 2:
            break
    assert active[0] == 2

    hold.set()
    await asyncio.wait_for(loop_task, timeout=2.0)
    assert len(queue.acked) == 3
