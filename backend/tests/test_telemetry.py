"""OpenTelemetry bootstrap and trace propagation on run jobs."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from opentelemetry import metrics
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from app.core.config import Settings

from app.core.telemetry import (
    capture_trace_context,
    is_enabled,
    record_queue_metrics,
    set_worker_utilization,
    setup_telemetry,
    shutdown_telemetry,
)
from app.worker.queue import QueueStats, RunJob


@pytest.fixture(autouse=True)
def _reset_otel():
    shutdown_telemetry()
    yield
    shutdown_telemetry()


def test_otel_disabled_by_default():
    assert not is_enabled()
    assert capture_trace_context() is None


def test_setup_telemetry_noop_when_disabled():
    setup_telemetry(settings=Settings(otel_enabled=False))
    assert capture_trace_context() is None


def test_runjob_trace_context_round_trip():
    ctx = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    job = RunJob.new(
        run_id="r1",
        agent_id="a1",
        adapter="echo",
        trace_context=ctx,
    )
    payload = job.to_json()
    assert "trace_context" in payload
    restored = RunJob.from_json(payload)
    assert restored.trace_context == ctx


def test_runjob_omits_empty_trace_context():
    job = RunJob.new(
        run_id="r1",
        agent_id="a1",
        adapter="echo",
        trace_context=None,
    )
    data = json.loads(job.to_json())
    assert "trace_context" not in data


def test_queue_metrics_noop_when_disabled():
    record_queue_metrics(
        QueueStats(
            stream_length=5,
            lag_count=3,
            pending_count=2,
            oldest_lag_seconds=1.0,
            oldest_pending_idle_seconds=None,
            dlq_length=0,
        )
    )


def test_worker_utilization_noop_when_disabled():
    set_worker_utilization(in_flight=2, capacity=4)


def _metric_values(reader: InMemoryMetricReader) -> dict[str, float]:
    provider = metrics.get_meter_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[union-attr]
    data = reader.get_metrics_data()
    if data is None:
        return {}
    values: dict[str, float] = {}
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                for point in metric.data.data_points:
                    values[metric.name] = float(point.value)  # type: ignore[attr-defined]
    return values


def test_otel_queue_and_worker_gauges_export():
    reader = InMemoryMetricReader()
    settings = Settings(otel_enabled=True, otel_service_name="test-metrics")
    with patch("app.core.telemetry.get_settings", return_value=settings):
        setup_telemetry(settings=settings, metric_readers=[reader])
        record_queue_metrics(
            QueueStats(
                stream_length=10,
                lag_count=4,
                pending_count=1,
                oldest_lag_seconds=30.0,
                oldest_pending_idle_seconds=5.0,
                dlq_length=2,
            )
        )
        set_worker_utilization(in_flight=3, capacity=4)
        exported = _metric_values(reader)
        assert exported["agentflow.queue.backlog"] == 5.0
        assert exported["agentflow.queue.consumer_delay"] == 30.0
        assert exported["agentflow.worker.in_flight"] == 3.0
        assert exported["agentflow.worker.utilization"] == 0.75
