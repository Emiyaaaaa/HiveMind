"""Tests for LLM working-memory window trimming."""

from __future__ import annotations

from app.runtime.memory_window import (
    fit_messages_to_window,
    parse_memory_config,
)


def test_parse_memory_config_defaults():
    cfg = parse_memory_config({})
    assert cfg.window_tokens == 0
    assert cfg.summarize is False


def test_parse_memory_config_reads_agent_config():
    cfg = parse_memory_config(
        {"memory": {"window_tokens": 4000, "summarize": True}}
    )
    assert cfg.window_tokens == 4000
    assert cfg.summarize is True


def test_fit_messages_noop_when_disabled():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert fit_messages_to_window(messages, window_tokens=0, summarize=False) == messages


def test_fit_messages_keeps_recent_turns():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a" * 400},
        {"role": "assistant", "content": "b" * 400},
        {"role": "user", "content": "recent"},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=120, summarize=False)
    assert trimmed[0]["role"] == "system"
    assert trimmed[-1]["content"] == "recent"
    assert len(trimmed) < len(messages)


def test_fit_messages_summarizes_dropped_turns():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old question " * 50},
        {"role": "assistant", "content": "old answer " * 50},
        {"role": "user", "content": "new"},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=80, summarize=True)
    assert trimmed[0]["role"] == "system"
    assert any(
        m.get("role") == "system" and "Earlier conversation summary" in str(m.get("content"))
        for m in trimmed
    )
    assert trimmed[-1]["content"] == "new"
