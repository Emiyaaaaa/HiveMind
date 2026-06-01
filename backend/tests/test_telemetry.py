"""OpenTelemetry bootstrap and trace propagation on run jobs."""

from __future__ import annotations

import json

import pytest

from app.core.config import Settings
from app.core.telemetry import (
    capture_trace_context,
    is_enabled,
    setup_telemetry,
    shutdown_telemetry,
)
from app.worker.queue import RunJob


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
