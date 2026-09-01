"""Tests for working-memory volume metrics and threshold alerts."""

from __future__ import annotations

from app.runtime.memory_metrics import (
    _active_alerts,
    checkpoint_state_bytes,
    clear_memory_alerts,
    estimate_prompt_tokens_from_history,
    maybe_alert_checkpoint_bytes,
    maybe_alert_messages_per_run,
    maybe_alert_prompt_tokens_from_history,
)


def setup_function() -> None:
    _active_alerts.clear()


def test_checkpoint_state_bytes():
    payload = {"graph_state": {"reply": "done", "completed_nodes": ["draft"]}}
    assert checkpoint_state_bytes(payload) > 0


def test_estimate_prompt_tokens_from_history():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hello"},
    ]
    assert estimate_prompt_tokens_from_history(messages) == 0

    messages.extend(
        [
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "again"},
        ]
    )
    assert estimate_prompt_tokens_from_history(messages) > 0


def test_memory_alert_edge_triggering():
    active = len(_active_alerts)
    maybe_alert_checkpoint_bytes(
        run_id="run-1",
        adapter="langgraph",
        checkpoint_bytes=300_000,
    )
    assert len(_active_alerts) == active + 1

    maybe_alert_checkpoint_bytes(
        run_id="run-1",
        adapter="langgraph",
        checkpoint_bytes=300_000,
    )
    assert len(_active_alerts) == active + 1

    maybe_alert_checkpoint_bytes(
        run_id="run-1",
        adapter="langgraph",
        checkpoint_bytes=100,
    )
    assert len(_active_alerts) == active

    clear_memory_alerts("run-1")
    assert not any(key[0] == "run-1" for key in _active_alerts)


def test_messages_and_prompt_alerts_use_distinct_kinds():
    maybe_alert_messages_per_run(
        run_id="run-2",
        adapter="langgraph",
        message_count=1000,
    )
    maybe_alert_prompt_tokens_from_history(
        run_id="run-2",
        adapter="langgraph",
        tokens=9000,
        step_index=3,
    )
    assert ("run-2", "messages_per_run") in _active_alerts
    assert ("run-2", "prompt_tokens_from_history") in _active_alerts
