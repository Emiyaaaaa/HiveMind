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


def test_parse_memory_config_clamps_invalid_tokens():
    cfg = parse_memory_config({"memory": {"window_tokens": "nope", "summarize": 1}})
    assert cfg.window_tokens == 0
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


def test_fit_messages_pins_all_system_messages():
    messages = [
        {"role": "system", "content": "sys-a"},
        {"role": "user", "content": "old " * 80},
        {"role": "system", "content": "sys-b"},
        {"role": "assistant", "content": "mid " * 80},
        {"role": "user", "content": "recent"},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=100, summarize=False)
    systems = [m for m in trimmed if m.get("role") == "system"]
    assert {m["content"] for m in systems} >= {"sys-a", "sys-b"}
    assert trimmed[-1]["content"] == "recent"


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


def test_fit_messages_repairs_orphan_tool_head():
    assistant_tools = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_1", "name": "search", "arguments": "{}"}],
    }
    tool_msg = {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "result " * 40,
    }
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old " * 80},
        assistant_tools,
        tool_msg,
        {"role": "user", "content": "follow-up"},
    ]
    # Budget small enough that greedy starts at the tool/follow-up side.
    trimmed = fit_messages_to_window(messages, window_tokens=90, summarize=False)
    assert trimmed[0]["role"] == "system"
    non_system = [m for m in trimmed if m.get("role") != "system"]
    assert non_system[0].get("tool_calls") or non_system[0].get("role") != "tool"
    if any(m.get("role") == "tool" for m in non_system):
        # Orphan tool must not lead the non-system window.
        assert non_system[0].get("role") == "assistant"
        assert non_system[0].get("tool_calls")


def test_fit_messages_summarize_does_not_leave_orphan_tool():
    assistant_tools = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_1", "name": "search", "arguments": "{}"}],
    }
    tool_msg = {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "tool-result " * 30,
    }
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "ancient " * 60},
        assistant_tools,
        tool_msg,
        {"role": "assistant", "content": "final " * 40},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=70, summarize=True)
    non_system = [m for m in trimmed if m.get("role") != "system"]
    assert not non_system or non_system[0].get("role") != "tool"
    assert any(
        m.get("role") == "system" and "Earlier conversation summary" in str(m.get("content"))
        for m in trimmed
    )
