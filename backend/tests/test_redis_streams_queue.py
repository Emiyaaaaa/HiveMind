"""Behavioural tests for ``RedisStreamsJobQueue``.

These exercise the at-least-once delivery contract end-to-end against a
``fakeredis.aioredis.FakeRedis`` instance, which is good enough to cover
``XADD`` / ``XREADGROUP`` / ``XACK`` / ``XAUTOCLAIM`` / ``XPENDING`` flow.
The real Redis path is exercised in deployment smoke tests and is too slow
to run in the unit test suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

import fakeredis.aioredis as fakeredis
import pytest

from app.worker.queue import JobLease, RedisStreamsJobQueue, RunJob


def _make_queue(
    redis_client: Any,
    *,
    consumer: str = "consumer-a",
    claim_idle_ms: int = 0,
    max_deliveries: int = 3,
) -> RedisStreamsJobQueue:
    return RedisStreamsJobQueue(
        redis_client=redis_client,
        stream_key="test:agentflow:jobs:runs",
        group="agentflow-workers",
        consumer=consumer,
        block_ms=50,
        claim_idle_ms=claim_idle_ms,
        max_deliveries=max_deliveries,
        dlq_key="test:agentflow:jobs:runs:dlq",
    )


async def _take_one(queue: RedisStreamsJobQueue) -> JobLease:
    """Pull a single lease from ``queue.consume`` with a short timeout."""
    consumer = queue.consume()
    return await asyncio.wait_for(consumer.__anext__(), timeout=1.0)


@pytest.mark.asyncio
async def test_xadd_xreadgroup_round_trip():
    redis = fakeredis.FakeRedis(decode_responses=True)
    queue = _make_queue(redis)

    job = RunJob.new(run_id="r1", agent_id="a1", adapter="echo")
    await queue.enqueue(job)

    lease = await _take_one(queue)
    assert lease.job.run_id == "r1"
    assert lease.token is not None
    assert lease.delivery_count == 1


@pytest.mark.asyncio
async def test_ack_removes_from_pending_list():
    redis = fakeredis.FakeRedis(decode_responses=True)
    queue = _make_queue(redis)

    await queue.enqueue(RunJob.new(run_id="r1", agent_id="a1", adapter="echo"))
    lease = await _take_one(queue)

    pending_before = await redis.xpending(queue._stream, queue._group)
    assert pending_before["pending"] == 1

    await queue.ack(lease)

    pending_after = await redis.xpending(queue._stream, queue._group)
    assert pending_after["pending"] == 0


@pytest.mark.asyncio
async def test_unacked_entry_is_reclaimed_by_other_consumer():
    """Simulates a worker that XREADGROUPed an entry then crashed.

    The second consumer must be able to XAUTOCLAIM and finish the job.
    """
    redis = fakeredis.FakeRedis(decode_responses=True)
    producer = _make_queue(redis, consumer="dead-worker")
    survivor = _make_queue(redis, consumer="survivor")

    await producer.enqueue(RunJob.new(run_id="r-claim", agent_id="a", adapter="echo"))

    # First consumer reads but never ACKs (simulates crash).
    leaked = await _take_one(producer)
    assert leaked.token is not None

    # Survivor reclaims and sees a delivery_count > 1.
    reclaimed = await _take_one(survivor)
    assert reclaimed.job.run_id == "r-claim"
    assert reclaimed.token == leaked.token
    assert reclaimed.delivery_count >= 2

    await survivor.ack(reclaimed)
    pending = await redis.xpending(survivor._stream, survivor._group)
    assert pending["pending"] == 0


@pytest.mark.asyncio
async def test_poison_message_is_dead_lettered_after_max_deliveries():
    redis = fakeredis.FakeRedis(decode_responses=True)
    queue = _make_queue(redis, consumer="c0", max_deliveries=2)

    await queue.enqueue(RunJob.new(run_id="r-poison", agent_id="a", adapter="echo"))

    # Drive the lifecycle with one long-lived consumer instead of re-creating
    # the generator each cycle: the first __anext__ delivers via XREADGROUP,
    # subsequent ones return reclaimed leases with bumped delivery_count.
    consumer = queue.consume()
    try:
        first = await asyncio.wait_for(consumer.__anext__(), timeout=1.0)
        assert first.delivery_count == 1
        second = await asyncio.wait_for(consumer.__anext__(), timeout=1.0)
        assert second.delivery_count == 2
        # Third claim attempt exceeds max_deliveries (2) -> entry is routed
        # to the DLQ inside _reap_stale and never yields again.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(consumer.__anext__(), timeout=0.3)
    finally:
        await consumer.aclose()

    dlq_entries = await redis.xrange(queue._dlq)
    assert len(dlq_entries) == 1
    _, fields = dlq_entries[0]
    assert "payload" in fields
    assert int(fields["_deliveries"]) >= 3

    pending = await redis.xpending(queue._stream, queue._group)
    assert pending["pending"] == 0


@pytest.mark.asyncio
async def test_malformed_entry_is_acked_not_replayed():
    redis = fakeredis.FakeRedis(decode_responses=True)
    queue = _make_queue(redis)

    # Bypass the queue and inject a malformed entry directly on the stream.
    await queue._ensure_group()
    await redis.xadd(queue._stream, {"payload": "{not json"})

    consumer = queue.consume()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(consumer.__anext__(), timeout=0.3)
    finally:
        await consumer.aclose()

    pending = await redis.xpending(queue._stream, queue._group)
    assert pending["pending"] == 0
