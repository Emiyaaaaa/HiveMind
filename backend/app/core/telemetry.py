"""OpenTelemetry bootstrap: distributed traces and RED metrics.

RED (Rate, Errors, Duration) is exported via OTLP when ``AGENTFLOW_OTEL_ENABLED``
is true. Instrumentation spans:

* HTTP API (FastAPI middleware)
* Worker job processing (``worker.process_job``)
* Adapter execution (``adapter.run``)

Trace context is propagated from API → Redis job payload → worker via W3C
``traceparent`` / ``tracestate`` in ``RunJob.trace_context``.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TypeVar

from opentelemetry import metrics, trace
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.propagate import extract, inject, set_global_textmap
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.worker.queue import QueueStats

logger = get_logger("telemetry")

F = TypeVar("F", bound=Callable[..., Any])
AF = TypeVar("AF", bound=Callable[..., Awaitable[Any]])

_tracer: Tracer | None = None
_meter: Meter | None = None
_initialized = False

# RED metric instruments (lazy-created on first use).
_http_requests: Counter | None = None
_http_errors: Counter | None = None
_http_duration: Histogram | None = None
_worker_jobs: Counter | None = None
_worker_errors: Counter | None = None
_worker_duration: Histogram | None = None
_adapter_runs: Counter | None = None
_adapter_errors: Counter | None = None
_adapter_duration: Histogram | None = None
_queue_stream_length: Any | None = None
_queue_lag: Any | None = None
_queue_pending: Any | None = None
_queue_backlog: Any | None = None
_queue_consumer_delay: Any | None = None
_queue_dlq_length: Any | None = None
_worker_utilization: Any | None = None
_worker_in_flight: Any | None = None
_worker_capacity: Any | None = None


def is_enabled() -> bool:
    return get_settings().otel_enabled


def _resource(settings: Settings) -> Resource:
    return Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.otel_service_version,
        }
    )


def _otlp_endpoint(settings: Settings) -> str:
    base = (settings.otel_exporter_endpoint or "http://localhost:4318").rstrip("/")
    return base


def setup_telemetry(
    *,
    settings: Settings | None = None,
    metric_readers: list[MetricReader] | None = None,
) -> None:
    """Idempotent SDK setup. No-op when ``otel_enabled`` is false."""
    global _initialized, _tracer, _meter

    settings = settings or get_settings()
    if not settings.otel_enabled:
        return
    if _initialized:
        return

    resource = _resource(settings)
    endpoint = _otlp_endpoint(settings)

    tracer_provider = TracerProvider(resource=resource)
    if metric_readers is None:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"),
            )
        )
    trace.set_tracer_provider(tracer_provider)

    if metric_readers is None:
        metric_reader: MetricReader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
            export_interval_millis=settings.otel_metric_export_interval_ms,
        )
        readers: list[MetricReader] = [metric_reader]
    else:
        readers = metric_readers
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)

    set_global_textmap(TraceContextTextMapPropagator())

    _tracer = trace.get_tracer(settings.otel_service_name)
    _meter = metrics.get_meter(settings.otel_service_name)
    _initialized = True
    logger.info(
        "otel.initialized",
        service=settings.otel_service_name,
        endpoint=endpoint,
    )


def shutdown_telemetry() -> None:
    """Flush exporters on process exit."""
    global _initialized, _tracer, _meter
    global _http_requests, _http_errors, _http_duration
    global _worker_jobs, _worker_errors, _worker_duration
    global _adapter_runs, _adapter_errors, _adapter_duration
    global _queue_stream_length, _queue_lag, _queue_pending, _queue_backlog
    global _queue_consumer_delay, _queue_dlq_length
    global _worker_utilization, _worker_in_flight, _worker_capacity

    if not _initialized:
        return

    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "shutdown"):
        tracer_provider.shutdown()  # type: ignore[union-attr]

    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
        meter_provider.shutdown()  # type: ignore[union-attr]

    # Reset globals so a later setup_telemetry() in tests or respawns can run.
    trace.set_tracer_provider(TracerProvider())
    metrics.set_meter_provider(NoOpMeterProvider())

    _initialized = False
    _tracer = None
    _meter = None
    _http_requests = None
    _http_errors = None
    _http_duration = None
    _worker_jobs = None
    _worker_errors = None
    _worker_duration = None
    _adapter_runs = None
    _adapter_errors = None
    _adapter_duration = None
    _queue_stream_length = None
    _queue_lag = None
    _queue_pending = None
    _queue_backlog = None
    _queue_consumer_delay = None
    _queue_dlq_length = None
    _worker_utilization = None
    _worker_in_flight = None
    _worker_capacity = None


def get_tracer() -> Tracer:
    setup_telemetry()
    return _tracer or trace.get_tracer(get_settings().otel_service_name)


def _ensure_red_instruments() -> None:
    global _http_requests, _http_errors, _http_duration
    global _worker_jobs, _worker_errors, _worker_duration
    global _adapter_runs, _adapter_errors, _adapter_duration

    if _meter is None:
        setup_telemetry()
    meter = _meter or metrics.get_meter(get_settings().otel_service_name)

    if _http_requests is None:
        _http_requests = meter.create_counter(
            "agentflow.http.server.requests",
            description="HTTP requests (rate)",
            unit="1",
        )
        _http_errors = meter.create_counter(
            "agentflow.http.server.errors",
            description="HTTP server errors (5xx and unhandled)",
            unit="1",
        )
        _http_duration = meter.create_histogram(
            "agentflow.http.server.duration",
            description="HTTP request duration",
            unit="s",
        )
        _worker_jobs = meter.create_counter(
            "agentflow.worker.jobs",
            description="Worker jobs processed (rate)",
            unit="1",
        )
        _worker_errors = meter.create_counter(
            "agentflow.worker.job.errors",
            description="Worker job failures before ACK",
            unit="1",
        )
        _worker_duration = meter.create_histogram(
            "agentflow.worker.job.duration",
            description="Worker job end-to-end duration",
            unit="s",
        )
        _adapter_runs = meter.create_counter(
            "agentflow.adapter.runs",
            description="Adapter run invocations (rate)",
            unit="1",
        )
        _adapter_errors = meter.create_counter(
            "agentflow.adapter.run.errors",
            description="Adapter run failures",
            unit="1",
        )
        _adapter_duration = meter.create_histogram(
            "agentflow.adapter.run.duration",
            description="Adapter run duration",
            unit="s",
        )


def _ensure_queue_instruments() -> None:
    global _queue_stream_length, _queue_lag, _queue_pending, _queue_backlog
    global _queue_consumer_delay, _queue_dlq_length

    if _meter is None:
        setup_telemetry()
    meter = _meter or metrics.get_meter(get_settings().otel_service_name)

    if _queue_stream_length is None:
        _queue_stream_length = meter.create_gauge(
            "agentflow.queue.stream_length",
            description="Redis stream entry count (XLEN)",
            unit="1",
        )
        _queue_lag = meter.create_gauge(
            "agentflow.queue.lag",
            description="Undelivered entries not yet assigned to a consumer",
            unit="1",
        )
        _queue_pending = meter.create_gauge(
            "agentflow.queue.pending",
            description="Entries delivered but not yet XACKed",
            unit="1",
        )
        _queue_backlog = meter.create_gauge(
            "agentflow.queue.backlog",
            description="lag + pending (work waiting on workers)",
            unit="1",
        )
        _queue_consumer_delay = meter.create_gauge(
            "agentflow.queue.consumer_delay",
            description="Worst-case wait among lag and pending entries",
            unit="s",
        )
        _queue_dlq_length = meter.create_gauge(
            "agentflow.queue.dlq_length",
            description="Dead-letter stream length",
            unit="1",
        )


def _ensure_worker_util_instruments() -> None:
    global _worker_utilization, _worker_in_flight, _worker_capacity

    if _meter is None:
        setup_telemetry()
    meter = _meter or metrics.get_meter(get_settings().otel_service_name)

    if _worker_utilization is None:
        _worker_utilization = meter.create_gauge(
            "agentflow.worker.utilization",
            description=(
                "Fraction of local concurrency slots busy (in_flight / capacity)"
            ),
            unit="1",
        )
        _worker_in_flight = meter.create_gauge(
            "agentflow.worker.in_flight",
            description="Run jobs currently executing in this worker process",
            unit="1",
        )
        _worker_capacity = meter.create_gauge(
            "agentflow.worker.capacity",
            description="Maximum parallel jobs (AGENTFLOW_WORKER_CONCURRENCY)",
            unit="1",
        )


def record_queue_metrics(stats: "QueueStats") -> None:
    """Export a queue monitor sample as OTel gauges (``agentflow.queue.*``)."""
    if not is_enabled():
        return
    _ensure_queue_instruments()
    assert _queue_stream_length is not None
    assert _queue_lag is not None
    assert _queue_pending is not None
    assert _queue_backlog is not None
    assert _queue_consumer_delay is not None
    assert _queue_dlq_length is not None

    _queue_stream_length.set(stats.stream_length)
    _queue_lag.set(stats.lag_count)
    _queue_pending.set(stats.pending_count)
    _queue_backlog.set(stats.backlog_count)
    delay = stats.consumer_delay_seconds
    if delay is not None:
        _queue_consumer_delay.set(delay)
    if stats.dlq_length is not None:
        _queue_dlq_length.set(stats.dlq_length)


def set_worker_utilization(*, in_flight: int, capacity: int) -> None:
    """Update per-process worker slot usage (``agentflow.worker.*`` gauges)."""
    if not is_enabled():
        return
    _ensure_worker_util_instruments()
    assert _worker_utilization is not None
    assert _worker_in_flight is not None
    assert _worker_capacity is not None

    capped = max(0, in_flight)
    slots = max(1, capacity)
    ratio = min(capped, slots) / slots
    _worker_in_flight.set(capped)
    _worker_capacity.set(capacity)
    _worker_utilization.set(ratio)


def capture_trace_context() -> dict[str, str] | None:
    """Serialize the active span context for cross-process propagation."""
    if not is_enabled():
        return None
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier or None


def instrument_fastapi(app: Any) -> None:
    """Attach FastAPI auto-instrumentation and RED middleware."""
    if not is_enabled():
        return
    setup_telemetry()
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/v1/health,/",
        tracer_provider=trace.get_tracer_provider(),
        meter_provider=metrics.get_meter_provider(),
    )


def record_http_red(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    if not is_enabled():
        return
    _ensure_red_instruments()
    attrs = {
        "http.method": method,
        "http.route": route,
        "http.status_code": status_code,
    }
    assert _http_requests is not None
    assert _http_duration is not None
    _http_requests.add(1, attributes=attrs)
    _http_duration.record(duration_seconds, attributes=attrs)
    if status_code >= 500:
        assert _http_errors is not None
        _http_errors.add(1, attributes=attrs)


def record_worker_red(
    *,
    adapter: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    if not is_enabled():
        return
    _ensure_red_instruments()
    attrs = {"adapter": adapter, "outcome": outcome}
    assert _worker_jobs is not None
    assert _worker_duration is not None
    _worker_jobs.add(1, attributes=attrs)
    _worker_duration.record(duration_seconds, attributes=attrs)
    if outcome == "error":
        assert _worker_errors is not None
        _worker_errors.add(1, attributes=attrs)


def record_adapter_red(
    *,
    adapter: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    if not is_enabled():
        return
    _ensure_red_instruments()
    attrs = {"adapter": adapter, "outcome": outcome}
    assert _adapter_runs is not None
    assert _adapter_duration is not None
    _adapter_runs.add(1, attributes=attrs)
    _adapter_duration.record(duration_seconds, attributes=attrs)
    if outcome == "error":
        assert _adapter_errors is not None
        _adapter_errors.add(1, attributes=attrs)


@contextmanager
def span(
    name: str,
    *,
    attributes: Mapping[str, str | int | float | bool] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    parent_context: Mapping[str, str] | None = None,
):
    """Context manager for a traced block with optional remote parent."""
    if not is_enabled():
        yield None
        return

    ctx = extract(parent_context or {}) if parent_context else None
    tracer = get_tracer()
    with tracer.start_as_current_span(
        name,
        context=ctx,
        kind=kind,
        attributes=dict(attributes or {}),
    ) as otel_span:
        try:
            yield otel_span
        except Exception as exc:
            if otel_span is not None:
                otel_span.record_exception(exc)
                otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


async def trace_adapter_run(
    adapter_name: str,
    run_id: str,
    coro: Awaitable[Any],
) -> Any:
    """Run ``adapter.run`` inside a span with RED metrics."""
    if not is_enabled():
        return await coro

    start = time.perf_counter()
    outcome = "ok"
    try:
        with span(
            "adapter.run",
            attributes={"adapter": adapter_name, "run.id": run_id},
            kind=SpanKind.INTERNAL,
        ):
            return await coro
    except Exception:
        outcome = "error"
        raise
    finally:
        record_adapter_red(
            adapter=adapter_name,
            outcome=outcome,
            duration_seconds=time.perf_counter() - start,
        )


async def trace_worker_job(
    *,
    adapter: str,
    run_id: str,
    trace_context: Mapping[str, str] | None,
    coro: Awaitable[Any],
) -> Any:
    """Run a leased job inside a consumer span linked to the API trace."""
    if not is_enabled():
        return await coro

    start = time.perf_counter()
    outcome = "ok"
    try:
        with span(
            "worker.process_job",
            attributes={"adapter": adapter, "run.id": run_id},
            kind=SpanKind.CONSUMER,
            parent_context=trace_context,
        ):
            return await coro
    except Exception:
        outcome = "error"
        raise
    finally:
        record_worker_red(
            adapter=adapter,
            outcome=outcome,
            duration_seconds=time.perf_counter() - start,
        )
