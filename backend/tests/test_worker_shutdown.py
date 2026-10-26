"""Shutdown must interrupt queue waits and finish leases already received."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import Settings
from app.worker.queue import JobLease, RunJob
from app.worker.runner import _consume_loop


class BlockingQueue:
    def __init__(self, leases: list[JobLease] | None = None) -> None:
        self.leases = leases or []
        self.reading = asyncio.Event()
        self.closed = asyncio.Event()
        self.acked: list[JobLease] = []
        self.received = 0
        self.reader_task: asyncio.Task | None = None

    async def consume(self):
        try:
            for lease in self.leases:
                self.received += 1
                yield lease
            self.reader_task = asyncio.current_task()
            self.reading.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover - blocked reader never produces a lease
        finally:
            self.closed.set()

    async def ack(self, lease: JobLease) -> None:
        self.acked.append(lease)


class UnexpectedExecutor:
    async def execute(self, run_id: str, adapter: str) -> None:
        raise AssertionError("an idle worker must not execute a job")


async def test_idle_worker_exits_when_stop_is_set():
    queue = BlockingQueue()
    stop = asyncio.Event()
    task = asyncio.create_task(
        _consume_loop(
            executor=UnexpectedExecutor(),
            queue=queue,
            stop=stop,
            concurrency=1,
        )
    )
    try:
        await asyncio.wait_for(queue.reading.wait(), timeout=1)
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        assert queue.closed.is_set()
        assert queue.acked == []
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def make_lease(run_id: str = "run-1") -> JobLease:
    return JobLease(
        job=RunJob.new(run_id=run_id, agent_id="agent-1", adapter="echo"),
        token=run_id,
    )


class HoldingExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.runs: list[str] = []
        self.cancelled = False

    async def execute(self, run_id: str, adapter: str) -> None:
        self.runs.append(run_id)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.parametrize("concurrency", [1, 2])
async def test_stop_interrupts_wait_and_drains_started_job(concurrency):
    lease = make_lease()
    queue = BlockingQueue([lease])
    executor = HoldingExecutor()
    stop = asyncio.Event()
    task = asyncio.create_task(
        _consume_loop(
            executor=executor,
            queue=queue,
            stop=stop,
            concurrency=concurrency,
        )
    )
    try:
        await asyncio.wait_for(executor.started.wait(), timeout=1)
        if concurrency == 2:
            await asyncio.wait_for(queue.reading.wait(), timeout=1)
        stop.set()
        # Closing must happen before the held job finishes: this exercises
        # either a blocked semaphore (1 slot) or a blocked queue read (2).
        await asyncio.wait_for(queue.closed.wait(), timeout=1)
        assert not task.done()
        assert not executor.cancelled
        assert queue.acked == []
        assert queue.received == 1
        executor.release.set()
        await asyncio.wait_for(task, timeout=1)
        assert executor.runs == [lease.job.run_id]
        assert queue.acked == [lease]
    finally:
        executor.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_worker_already_stopped_does_not_read_or_execute():
    queue = BlockingQueue([make_lease()])
    stop = asyncio.Event()
    stop.set()

    await _consume_loop(executor=UnexpectedExecutor(), queue=queue, stop=stop, concurrency=1)

    assert queue.received == 0
    assert queue.acked == []


@pytest.mark.parametrize("return_on_cancel", [False, True])
async def test_lease_returned_during_shutdown_is_executed_and_acked(return_on_cancel):
    lease = make_lease()
    stop = asyncio.Event()

    class RaceQueue(BlockingQueue):
        async def consume(self):
            try:
                if return_on_cancel:
                    self.reading.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        pass  # model a read completing while cancellation arrives
                else:
                    stop.set()
                yield lease
            finally:
                self.closed.set()

    class Executor:
        def __init__(self):
            self.runs = []

        async def execute(self, run_id, adapter):
            self.runs.append(run_id)

    queue = RaceQueue()
    executor = Executor()
    task = asyncio.create_task(
        _consume_loop(
            executor=executor,
            queue=queue,
            stop=stop,
            concurrency=1,
        )
    )
    try:
        if return_on_cancel:
            await asyncio.wait_for(queue.reading.wait(), timeout=1)
            stop.set()
        await asyncio.wait_for(task, timeout=1)
        assert executor.runs == [lease.job.run_id]
        assert queue.acked == [lease]
        assert queue.closed.is_set()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelling_consumer_reaps_blocked_reader_and_propagates():
    queue = BlockingQueue()
    task = asyncio.create_task(
        _consume_loop(
            executor=UnexpectedExecutor(),
            queue=queue,
            stop=asyncio.Event(),
            concurrency=1,
        )
    )
    try:
        await asyncio.wait_for(queue.reading.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert queue.closed.is_set()
        assert queue.reader_task is not None and queue.reader_task.done()
        assert queue.acked == []
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_queue_error_drains_owned_lease_before_propagating():
    lease = make_lease()
    executor = HoldingExecutor()

    class FailingQueue(BlockingQueue):
        async def consume(self):
            try:
                yield lease
                await executor.started.wait()
                raise RuntimeError("queue read failed")
            finally:
                self.closed.set()

    queue = FailingQueue()
    task = asyncio.create_task(
        _consume_loop(
            executor=executor,
            queue=queue,
            stop=asyncio.Event(),
            concurrency=2,
        )
    )
    try:
        await asyncio.wait_for(queue.closed.wait(), timeout=1)
        assert not task.done()
        assert not executor.cancelled
        executor.release.set()
        with pytest.raises(RuntimeError, match="queue read failed"):
            await asyncio.wait_for(task, timeout=1)
        assert queue.acked == [lease]
    finally:
        executor.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_iterator_close_error_still_drains_owned_lease():
    lease = make_lease()
    executor = HoldingExecutor()
    stop = asyncio.Event()
    reading = asyncio.Event()
    closing = asyncio.Event()

    class Iterator:
        def __init__(self):
            self.delivered = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.delivered:
                self.delivered = True
                return lease
            reading.set()
            await asyncio.Event().wait()
            raise StopAsyncIteration  # pragma: no cover - cancelled first

        async def aclose(self):
            closing.set()
            raise RuntimeError("iterator close failed")

    class Queue(BlockingQueue):
        def consume(self):
            return Iterator()

    queue = Queue()
    task = asyncio.create_task(
        _consume_loop(
            executor=executor,
            queue=queue,
            stop=stop,
            concurrency=2,
        )
    )
    try:
        await asyncio.wait_for(reading.wait(), timeout=1)
        await asyncio.wait_for(executor.started.wait(), timeout=1)
        stop.set()
        await asyncio.wait_for(closing.wait(), timeout=1)
        assert not task.done()
        executor.release.set()
        with pytest.raises(RuntimeError, match="iterator close failed"):
            await asyncio.wait_for(task, timeout=1)
        assert queue.acked == [lease]
    finally:
        executor.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("monitor_enabled", [False, True])
async def test_worker_error_stops_all_sweepers_and_closes_resources(monkeypatch, monitor_enabled):
    from app.worker import runner

    settings = Settings(job_queue_monitor_enabled=monitor_enabled, data_retention_tenant_ttl_days=1)
    queue = Mock(aclose=AsyncMock())
    registry = Mock(aclose=AsyncMock())
    bus = Mock(aclose=AsyncMock())
    dispatcher = Mock(aclose=AsyncMock())
    db_engine = Mock(dispose=AsyncMock())
    started = asyncio.Event()
    background: list[asyncio.Task] = []
    finished: list[str] = []

    async def sweeper(*args, **kwargs):
        stop = args[-1]
        background.append(asyncio.current_task())
        if len(background) == (3 if monitor_enabled else 2):
            started.set()
        await stop.wait()
        finished.append("stopped")

    async def failed_consume(**kwargs):
        await started.wait()
        raise RuntimeError("worker queue unavailable")

    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "jobs_backend", lambda: "streams")
    monkeypatch.setattr(runner, "_ensure_schema", AsyncMock())
    monkeypatch.setattr(runner, "_consume_loop", failed_consume)
    monkeypatch.setattr(runner, "run_queue_monitor", sweeper)
    monkeypatch.setattr(runner, "run_retention_sweeper", sweeper)
    monkeypatch.setattr(runner, "run_schedule_sweeper", sweeper)
    monkeypatch.setattr(runner, "get_job_queue", lambda: queue)
    monkeypatch.setattr(runner, "get_cancel_registry", lambda: registry)
    monkeypatch.setattr(runner, "get_event_bus", lambda: bus)
    monkeypatch.setattr(runner, "get_webhook_dispatcher", lambda: dispatcher)
    monkeypatch.setattr(runner, "engine", db_engine)
    for name in ("setup_logging", "load_adapter_plugins", "setup_telemetry", "shutdown_telemetry"):
        monkeypatch.setattr(runner, name, Mock())
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *_: None)

    try:
        with pytest.raises(RuntimeError, match="worker queue unavailable"):
            await asyncio.wait_for(runner.run_forever(), timeout=1)
        assert len(finished) == (3 if monitor_enabled else 2)
        for resource in (dispatcher, queue, registry, bus):
            resource.aclose.assert_awaited_once()
        db_engine.dispose.assert_awaited_once()
    finally:
        for task in background:
            if not task.done():
                task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
