"""Tests for queue depth metrics and consumer-delay alerting."""

from __future__ import annotations

import asyncio
from typing import Any

import fakeredis.aioredis as fakeredis
import pytest

from unittest.mock import patch

from app.core.config import Settings
from app.worker.monitor import (
    _emit_delay_alerts,
    _emit_depth_alerts,
    collect_queue_stats,
    run_queue_monitor,
)
from app.worker.queue import QueueStats, RedisStreamsJobQueue, RunJob


def _make_queue(
    redis_client: Any,
    *,
    consumer: str = "monitor-test",
) -> RedisStreamsJobQueue:
    return RedisStreamsJobQueue(
        redis_client=redis_client,
        stream_key="test:monitor:jobs",
        group="agentflow-workers",
        consumer=consumer,
        block_ms=50,
        claim_idle_ms=0,
        max_deliveries=3,
        dlq_key="test:monitor:jobs:dlq",
    )


@pytest.mark.asyncio
async def test_collect_stats_reports_lag_for_undelivered_jobs():
    redis = fakeredis.FakeRedis(decode_responses=True)
    queue = _make_queue(redis)

    await queue.enqueue(RunJob.new(run_id="r1", agent_id="a1", adapter="echo"))
    await queue.enqueue(RunJob.new(run_id="r2", agent_id="a1", adapter="echo"))

    stats = await queue.collect_stats()
    assert stats is not None
    assert stats.stream_length == 2
    assert stats.lag_count == 2
    assert stats.pending_count == 0
    assert stats.oldest_lag_seconds is not None
    assert stats.oldest_lag_seconds >= 0.0
    assert stats.consumer_delay_seconds == stats.oldest_lag_seconds


@pytest.mark.asyncio
async def test_collect_stats_reports_pending_idle():
    redis = fakeredis.FakeRedis(decode_responses=True)
    queue = _make_queue(redis)

    await queue.enqueue(RunJob.new(run_id="r1", agent_id="a1", adapter="echo"))
    consumer = queue.consume()
    lease = await asyncio.wait_for(consumer.__anext__(), timeout=1.0)
    assert lease.token is not None

    stats = await queue.collect_stats()
    assert stats.pending_count == 1
    assert stats.lag_count == 0
    assert stats.oldest_pending_idle_seconds is not None
    assert stats.consumer_delay_seconds == stats.oldest_pending_idle_seconds


@pytest.mark.asyncio
async def test_collect_queue_stats_returns_none_for_in_memory_queue():
    from app.worker.queue import InMemoryJobQueue

    stats = await collect_queue_stats(InMemoryJobQueue())
    assert stats is None


def test_delay_alert_edge_triggering():
    stats = QueueStats(
        stream_length=1,
        lag_count=1,
        pending_count=0,
        oldest_lag_seconds=120.0,
        oldest_pending_idle_seconds=None,
    )

    active = _emit_delay_alerts(stats, threshold=60.0, active=False)
    assert active is True

    active = _emit_delay_alerts(stats, threshold=60.0, active=True)
    assert active is True

    cleared = QueueStats(
        stream_length=0,
        lag_count=0,
        pending_count=0,
        oldest_lag_seconds=None,
        oldest_pending_idle_seconds=None,
    )
    active = _emit_delay_alerts(cleared, threshold=60.0, active=True)
    assert active is False


def test_depth_alert_edge_triggering():
    stats = QueueStats(
        stream_length=10,
        lag_count=8,
        pending_count=2,
        oldest_lag_seconds=1.0,
        oldest_pending_idle_seconds=None,
    )

    active = _emit_depth_alerts(stats, threshold=5, active=False)
    assert active is True

    active = _emit_depth_alerts(stats, threshold=5, active=True)
    assert active is True

    cleared = QueueStats(
        stream_length=2,
        lag_count=2,
        pending_count=0,
        oldest_lag_seconds=0.5,
        oldest_pending_idle_seconds=None,
    )
    active = _emit_depth_alerts(cleared, threshold=5, active=True)
    assert active is False


@pytest.mark.asyncio
async def test_run_queue_monitor_exports_otel_metrics():
    redis = fakeredis.FakeRedis(decode_responses=True)
    queue = _make_queue(redis)
    await queue.enqueue(RunJob.new(run_id="r1", agent_id="a1", adapter="echo"))

    stop = asyncio.Event()
    settings = Settings(
        job_queue_monitor_enabled=True,
        job_queue_monitor_interval_seconds=5,
    )
    with patch("app.worker.monitor.record_queue_metrics") as record:
        monitor_task = asyncio.create_task(
            run_queue_monitor(queue, stop, settings=settings)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(monitor_task, timeout=1.0)

    assert record.call_count >= 1
    stats = record.call_args[0][0]
    assert stats.stream_length >= 1


@pytest.mark.asyncio
async def test_run_queue_monitor_stops_when_event_is_set():
    redis = fakeredis.FakeRedis(decode_responses=True)
    queue = _make_queue(redis)
    stop = asyncio.Event()

    settings = Settings(
        job_queue_monitor_enabled=True,
        job_queue_monitor_interval_seconds=5,
    )
    monitor_task = asyncio.create_task(
        run_queue_monitor(queue, stop, settings=settings)
    )

    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(monitor_task, timeout=1.0)
