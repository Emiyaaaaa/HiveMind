"""Queue depth metrics, consumer-delay alerting, and worker p95 latency alerts.

The monitor runs as a background asyncio task alongside the job consume loop.
It periodically samples the run-job stream and emits:

* ``agentflow.queue.*`` OTel gauges when ``AGENTFLOW_OTEL_ENABLED=true``.
* ``queue.metrics`` at INFO — baseline depth / lag / pending counters.
* ``queue.consumer_delay_alert`` at WARNING — oldest undelivered or
  un-ACKed entry exceeds ``Settings.job_queue_consumer_delay_alert_seconds``.
* ``queue.depth_alert`` at WARNING — ``lag + pending`` exceeds
  ``Settings.job_queue_depth_alert_threshold``.
* ``worker.job_p95_alert`` at WARNING — rolling worker-job p95 exceeds
  ``Settings.worker_job_p95_alert_seconds`` once enough samples exist.

Alerts use edge-triggered logging so a sustained backlog does not spam logs
every poll interval; a matching ``*.resolved`` INFO line is emitted when the
condition clears.
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings, get_settings
from app.core.duration_window import DurationWindow
from app.core.logging import get_logger
from app.core.telemetry import get_worker_job_duration_window, record_queue_metrics
from app.worker.queue import JobQueue, QueueStats, RedisStreamsJobQueue

logger = get_logger("worker.monitor")


async def collect_queue_stats(queue: JobQueue) -> QueueStats | None:
    """Sample queue metrics. Returns ``None`` for non-stream implementations."""
    if not isinstance(queue, RedisStreamsJobQueue):
        return None
    return await queue.collect_stats()


async def run_queue_monitor(
    queue: JobQueue,
    stop: asyncio.Event,
    *,
    settings: Settings | None = None,
) -> None:
    """Poll queue metrics until ``stop`` is set."""
    settings = settings or get_settings()
    if not settings.job_queue_monitor_enabled:
        return

    interval = settings.job_queue_monitor_interval_seconds
    delay_alert_active = False
    depth_alert_active = False
    worker_p95_alert_active = False
    duration_window = get_worker_job_duration_window()

    while not stop.is_set():
        try:
            stats = await collect_queue_stats(queue)
            if stats is not None:
                record_queue_metrics(stats)
                logger.info(
                    "queue.metrics",
                    stream_length=stats.stream_length,
                    lag=stats.lag_count,
                    pending=stats.pending_count,
                    backlog=stats.backlog_count,
                    consumer_delay_seconds=stats.consumer_delay_seconds,
                    oldest_lag_seconds=stats.oldest_lag_seconds,
                    oldest_pending_idle_seconds=stats.oldest_pending_idle_seconds,
                    dlq_length=stats.dlq_length,
                )
                delay_alert_active = _emit_delay_alerts(
                    stats,
                    threshold=settings.job_queue_consumer_delay_alert_seconds,
                    active=delay_alert_active,
                )
                depth_alert_active = _emit_depth_alerts(
                    stats,
                    threshold=settings.job_queue_depth_alert_threshold,
                    active=depth_alert_active,
                )
            worker_p95_alert_active = _emit_worker_p95_alerts(
                duration_window,
                threshold=settings.worker_job_p95_alert_seconds,
                min_samples=settings.worker_job_p95_alert_min_samples,
                active=worker_p95_alert_active,
            )
        except Exception:  # pragma: no cover - defensive; monitor must not crash worker
            logger.exception("queue.monitor_failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            break
        except TimeoutError:
            continue


def _emit_delay_alerts(
    stats: QueueStats,
    *,
    threshold: float,
    active: bool,
) -> bool:
    delay = stats.consumer_delay_seconds
    breached = delay is not None and delay >= threshold
    if breached and not active:
        logger.warning(
            "queue.consumer_delay_alert",
            consumer_delay_seconds=delay,
            threshold_seconds=threshold,
            lag=stats.lag_count,
            pending=stats.pending_count,
            oldest_lag_seconds=stats.oldest_lag_seconds,
            oldest_pending_idle_seconds=stats.oldest_pending_idle_seconds,
        )
        return True
    if not breached and active:
        logger.info(
            "queue.consumer_delay_alert.resolved",
            consumer_delay_seconds=delay,
            threshold_seconds=threshold,
        )
        return False
    return active


def _emit_depth_alerts(
    stats: QueueStats,
    *,
    threshold: int,
    active: bool,
) -> bool:
    breached = stats.backlog_count >= threshold
    if breached and not active:
        logger.warning(
            "queue.depth_alert",
            backlog=stats.backlog_count,
            threshold=threshold,
            lag=stats.lag_count,
            pending=stats.pending_count,
            consumer_delay_seconds=stats.consumer_delay_seconds,
        )
        return True
    if not breached and active:
        logger.info(
            "queue.depth_alert.resolved",
            backlog=stats.backlog_count,
            threshold=threshold,
        )
        return False
    return active


def _emit_worker_p95_alerts(
    window: DurationWindow,
    *,
    threshold: float,
    min_samples: int,
    active: bool,
) -> bool:
    p95 = window.p95()
    sample_count = window.count()
    breached = (
        p95 is not None and sample_count >= min_samples and p95 >= threshold
    )
    if breached and not active:
        logger.warning(
            "worker.job_p95_alert",
            p95_seconds=p95,
            threshold_seconds=threshold,
            sample_count=sample_count,
        )
        return True
    if not breached and active:
        logger.info(
            "worker.job_p95_alert.resolved",
            p95_seconds=p95,
            threshold_seconds=threshold,
            sample_count=sample_count,
        )
        return False
    return active
