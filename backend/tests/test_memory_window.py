"""Tests for LLM working-memory window trimming."""

from __future__ import annotations

from app.runtime.memory_window import (
    SUMMARY_PREFIX,
    fit_messages_to_window,
    has_orphan_tool_head,
    parse_memory_config,
    _assistant_covers_leading_tools,
    _drop_oldest_kept_turn,
    _format_message_for_summary,
    _leading_tool_run_len,
    _messages_cost,
    _repair_tool_chain,
    _suffix_dropped,
    _summarize_dropped,
)


def _assistant_tools(
    call_id: str = "call_1",
    name: str = "search",
    *,
    extra: list[dict] | None = None,
) -> dict:
    tool_calls = [{"id": call_id, "name": name, "arguments": "{}"}]
    if extra:
        tool_calls.extend(extra)
    return {"role": "assistant", "content": "", "tool_calls": tool_calls}


def _tool_result(call_id: str = "call_1", content: str = "result") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


# --- parse_memory_config -------------------------------------------------


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


def test_parse_memory_config_clamps_negative_tokens():
    cfg = parse_memory_config({"memory": {"window_tokens": -100}})
    assert cfg.window_tokens == 0


def test_parse_memory_config_ignores_non_dict_memory():
    cfg = parse_memory_config({"memory": "window_tokens=8k"})
    assert cfg.window_tokens == 0
    assert cfg.summarize is False


def test_parse_memory_config_accepts_string_int_tokens():
    cfg = parse_memory_config({"memory": {"window_tokens": "2048", "summarize": False}})
    assert cfg.window_tokens == 2048
    assert cfg.summarize is False


# --- fit_messages_to_window: basics --------------------------------------


def test_fit_messages_noop_when_disabled():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert fit_messages_to_window(messages, window_tokens=0, summarize=False) == messages


def test_fit_messages_noop_when_empty():
    assert fit_messages_to_window([], window_tokens=100, summarize=True) == []


def test_fit_messages_noop_when_under_budget():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ]
    assert fit_messages_to_window(messages, window_tokens=10_000, summarize=True) == messages


def test_fit_messages_noop_when_only_system():
    messages = [
        {"role": "system", "content": "sys-a"},
        {"role": "system", "content": "sys-b"},
    ]
    assert fit_messages_to_window(messages, window_tokens=10, summarize=True) == messages


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
        m.get("role") == "system" and SUMMARY_PREFIX in str(m.get("content"))
        for m in trimmed
    )
    assert trimmed[-1]["content"] == "new"


def test_fit_messages_without_summarize_drops_quietly():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old question " * 50},
        {"role": "assistant", "content": "old answer " * 50},
        {"role": "user", "content": "new"},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=80, summarize=False)
    assert not any(SUMMARY_PREFIX in str(m.get("content") or "") for m in trimmed)
    assert trimmed[-1]["content"] == "new"


# --- tool-chain repair ---------------------------------------------------


def test_fit_messages_repairs_orphan_tool_head():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old " * 80},
        _assistant_tools(),
        _tool_result(content="result " * 40),
        {"role": "user", "content": "follow-up"},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=90, summarize=False)
    assert trimmed[0]["role"] == "system"
    non_system = [m for m in trimmed if m.get("role") != "system"]
    assert non_system[0].get("tool_calls") or non_system[0].get("role") != "tool"
    if any(m.get("role") == "tool" for m in non_system):
        assert non_system[0].get("role") == "assistant"
        assert non_system[0].get("tool_calls")


def test_fit_messages_summarize_does_not_leave_orphan_tool():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "ancient " * 60},
        _assistant_tools(),
        _tool_result(content="tool-result " * 30),
        {"role": "assistant", "content": "final " * 40},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=70, summarize=True)
    non_system = [m for m in trimmed if m.get("role") != "system"]
    assert not non_system or non_system[0].get("role") != "tool"
    assert any(
        m.get("role") == "system" and SUMMARY_PREFIX in str(m.get("content"))
        for m in trimmed
    )
    assert not has_orphan_tool_head(trimmed)


def test_fit_messages_repairs_parallel_tool_results():
    assistant = _assistant_tools(
        "call_a",
        "search",
        extra=[{"id": "call_b", "name": "lookup", "arguments": "{}"}],
    )
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old " * 100},
        assistant,
        _tool_result("call_a", "alpha " * 20),
        _tool_result("call_b", "beta " * 20),
        {"role": "user", "content": "next"},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=110, summarize=False)
    non_system = [m for m in trimmed if m.get("role") != "system"]
    assert not has_orphan_tool_head(trimmed)
    if any(m.get("role") == "tool" for m in non_system):
        assert non_system[0].get("role") == "assistant"
        ids = {tc.get("id") for tc in non_system[0].get("tool_calls") or []}
        assert {"call_a", "call_b"} <= ids


def test_fit_messages_summarize_drops_whole_tool_round():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "ancient " * 80},
        _assistant_tools("call_1", "search"),
        _tool_result("call_1", "payload " * 40),
        {"role": "assistant", "content": "done " * 50},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=55, summarize=True)
    assert not has_orphan_tool_head(trimmed)
    summary = next(
        m for m in trimmed if m.get("role") == "system" and SUMMARY_PREFIX in str(m.get("content"))
    )
    assert "tool" in str(summary["content"]).lower() or "search" in str(summary["content"])


def test_has_orphan_tool_head_detects_leading_tool():
    assert has_orphan_tool_head([_tool_result()]) is True
    assert has_orphan_tool_head(
        [{"role": "system", "content": "s"}, _tool_result()]
    ) is True
    assert has_orphan_tool_head(
        [{"role": "system", "content": "s"}, _assistant_tools(), _tool_result()]
    ) is False
    assert has_orphan_tool_head([{"role": "system", "content": "s"}]) is False


# --- helpers -------------------------------------------------------------


def test_summarize_dropped_includes_tool_call_names():
    text = _summarize_dropped(
        [
            {"role": "user", "content": "ask"},
            _assistant_tools("c1", "web_search"),
            _tool_result("c1", ""),
        ]
    )
    assert text.startswith(SUMMARY_PREFIX)
    assert "web_search" in text
    assert "tool" in text


def test_summarize_dropped_truncates_long_body():
    huge = [{"role": "user", "content": "x" * 500} for _ in range(20)]
    text = _summarize_dropped(huge)
    assert text.startswith(SUMMARY_PREFIX)
    assert text.endswith("...")
    assert len(text) < 2500


def test_format_message_for_summary_skips_empty():
    assert _format_message_for_summary({"role": "assistant", "content": ""}) is None
    assert _format_message_for_summary({"role": "user", "content": "hi"}) == "user: hi"


def test_leading_tool_run_len():
    msgs = [_tool_result("a"), _tool_result("b"), {"role": "user", "content": "u"}]
    assert _leading_tool_run_len(msgs) == 2
    assert _leading_tool_run_len([{"role": "user", "content": "u"}]) == 0
    assert _leading_tool_run_len([]) == 0


def test_assistant_covers_leading_tools():
    assistant = _assistant_tools(
        "a",
        "s",
        extra=[{"id": "b", "name": "t", "arguments": "{}"}],
    )
    assert _assistant_covers_leading_tools(
        assistant, [_tool_result("a"), _tool_result("b")]
    )
    assert not _assistant_covers_leading_tools(assistant, [_tool_result("missing")])
    assert not _assistant_covers_leading_tools(
        {"role": "assistant", "content": "plain"}, [_tool_result("a")]
    )


def test_repair_tool_chain_prepends_assistant_parent():
    rest = [
        {"role": "user", "content": "u"},
        _assistant_tools(),
        _tool_result(),
        {"role": "user", "content": "next"},
    ]
    kept = [_tool_result(), {"role": "user", "content": "next"}]
    repaired = _repair_tool_chain(rest, kept)
    assert repaired[0].get("role") == "assistant"
    assert repaired[1].get("role") == "tool"


def test_suffix_dropped_returns_prefix():
    rest = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    kept = [{"role": "user", "content": "b"}]
    assert _suffix_dropped(rest, kept) == [{"role": "user", "content": "a"}]
    assert _suffix_dropped(rest, []) == rest
    assert _suffix_dropped(rest, [{"role": "user", "content": "x"}]) == []


def test_drop_oldest_kept_turn_removes_tool_round():
    kept = [
        _assistant_tools(),
        _tool_result(content="r"),
        {"role": "assistant", "content": "final"},
    ]
    after = _drop_oldest_kept_turn(kept)
    assert after == [{"role": "assistant", "content": "final"}]


def test_drop_oldest_kept_turn_drops_orphan_tools():
    kept = [_tool_result(), {"role": "user", "content": "u"}]
    after = _drop_oldest_kept_turn(kept)
    assert after == [{"role": "user", "content": "u"}]


def test_messages_cost_positive_for_nonempty():
    assert _messages_cost([{"role": "user", "content": "hello world"}]) > 0
    assert _messages_cost([]) == 0


def test_fit_keeps_at_least_newest_turn_when_budget_tiny():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old " * 200},
        {"role": "assistant", "content": "mid " * 200},
        {"role": "user", "content": "newest"},
    ]
    trimmed = fit_messages_to_window(messages, window_tokens=1, summarize=False)
    assert trimmed[-1]["content"] == "newest"
    assert any(m.get("role") == "system" for m in trimmed)
