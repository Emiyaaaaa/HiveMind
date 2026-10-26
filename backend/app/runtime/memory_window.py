"""Working-memory window management for LLM prompts.

Agent config::

    {
      "memory": {
        "window_tokens": 8000,
        "summarize": true
      }
    }

When ``window_tokens`` is 0 (default) messages pass through unchanged.

Bounded context assembly pins every ``system`` message, then greedily keeps
the newest non-system turns under the token budget. Dropped turns can be
compacted into a system-level summary. After trimming, tool-call chains are
repaired so a window never starts on an orphan ``role=tool`` message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.runtime.tokens import estimate_tokens

SUMMARY_PREFIX = "[Earlier conversation summary]"
_SUMMARY_LINE_CHARS = 300
_SUMMARY_BODY_CHARS = 2000


@dataclass(frozen=True)
class MemoryWindowConfig:
    window_tokens: int = 0
    summarize: bool = False


def parse_memory_config(config: dict[str, Any]) -> MemoryWindowConfig:
    raw = config.get("memory")
    if not isinstance(raw, dict):
        return MemoryWindowConfig()
    window_tokens = raw.get("window_tokens", 0)
    try:
        window_tokens = int(window_tokens)
    except (TypeError, ValueError):
        window_tokens = 0
    return MemoryWindowConfig(
        window_tokens=max(0, window_tokens),
        summarize=bool(raw.get("summarize", False)),
    )


def _message_cost(message: dict[str, Any]) -> int:
    return estimate_tokens(json.dumps(message, default=str))


def _messages_cost(messages: list[dict[str, Any]]) -> int:
    return sum(_message_cost(m) for m in messages)


def _tool_call_names(message: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _tool_call_ids(message: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        call_id = str(tc.get("id") or "").strip()
        if call_id:
            ids.add(call_id)
    return ids


def _is_assistant_tool_call(message: dict[str, Any]) -> bool:
    return message.get("role") == "assistant" and bool(_tool_call_ids(message))


def _format_message_for_summary(message: dict[str, Any]) -> str | None:
    role = str(message.get("role") or "?")
    content = str(message.get("content") or "")
    if not content and message.get("tool_calls"):
        names = _tool_call_names(message)
        content = f"[tool_calls: {', '.join(names)}]" if names else "[tool_calls]"
    if not content and message.get("role") == "tool":
        call_id = str(message.get("tool_call_id") or "").strip()
        content = f"[tool result{f' {call_id}' if call_id else ''}]"
    if not content:
        return None
    return f"{role}: {content[:_SUMMARY_LINE_CHARS]}"


def _summarize_dropped(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        line = _format_message_for_summary(message)
        if line:
            parts.append(line)
    body = "\n".join(parts)
    if len(body) > _SUMMARY_BODY_CHARS:
        body = body[:_SUMMARY_BODY_CHARS] + "..."
    return f"{SUMMARY_PREFIX}\n{body}"


def _summary_message(dropped: list[dict[str, Any]]) -> dict[str, Any]:
    return {"role": "system", "content": _summarize_dropped(dropped)}


def _suffix_dropped(
    rest: list[dict[str, Any]], kept: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Messages in ``rest`` that sit before the kept suffix."""
    if not kept:
        return list(rest)
    start = len(rest) - len(kept)
    if start < 0 or rest[start:] != kept:
        # kept is not a clean suffix (should not happen); drop nothing extra.
        return []
    return rest[:start]


def _leading_tool_run_len(messages: list[dict[str, Any]]) -> int:
    """Count consecutive ``role=tool`` messages at the head of ``messages``."""
    count = 0
    for message in messages:
        if message.get("role") != "tool":
            break
        count += 1
    return count


def _assistant_covers_leading_tools(
    assistant: dict[str, Any], tools: list[dict[str, Any]]
) -> bool:
    """True when every leading tool message is answered by ``assistant``."""
    if not _is_assistant_tool_call(assistant) or not tools:
        return False
    covered = _tool_call_ids(assistant)
    for tool in tools:
        call_id = str(tool.get("tool_call_id") or "").strip()
        if call_id and call_id not in covered:
            return False
    return True


def _repair_tool_chain(
    rest: list[dict[str, Any]], kept: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ensure a leading tool run still has its assistant tool-call parent.

    Walks backward through ``rest`` while the window head is ``role=tool``,
    preferring to prepend the matching assistant ``tool_calls`` parent so
    OpenAI-compatible tool protocols stay valid (including parallel tools).
    """
    while kept:
        tool_run = _leading_tool_run_len(kept)
        if tool_run == 0:
            break
        idx = len(rest) - len(kept) - 1
        if idx < 0:
            break
        parent = rest[idx]
        leading_tools = kept[:tool_run]
        if _assistant_covers_leading_tools(parent, leading_tools):
            kept = [parent, *kept]
            break
        # Parent is another tool (or unrelated); keep walking upward.
        kept = [parent, *kept]
    return kept


def _drop_leading_orphan_tools(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When shrinking for budget, drop orphan tool heads instead of repairing up."""
    while kept and kept[0].get("role") == "tool":
        kept = kept[1:]
    return kept


def _drop_oldest_kept_turn(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the oldest kept turn, including a full assistant+tools round if needed."""
    if not kept:
        return kept
    if _is_assistant_tool_call(kept[0]):
        # Drop assistant tool-call parent together with its immediate tool results.
        drop_n = 1
        while drop_n < len(kept) and kept[drop_n].get("role") == "tool":
            drop_n += 1
        return kept[drop_n:]
    return _drop_leading_orphan_tools(kept[1:])


def has_orphan_tool_head(messages: list[dict[str, Any]]) -> bool:
    """Return True if the first non-system message is an orphan ``role=tool``."""
    for message in messages:
        if message.get("role") == "system":
            continue
        return message.get("role") == "tool"
    return False


def fit_messages_to_window(
    messages: list[dict[str, Any]],
    *,
    window_tokens: int,
    summarize: bool,
) -> list[dict[str, Any]]:
    """Keep system prompt + recent turns within a token budget."""
    if window_tokens <= 0 or not messages:
        return messages

    systems = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if not rest:
        return messages

    if _messages_cost(systems) + _messages_cost(rest) <= window_tokens:
        return messages

    kept: list[dict[str, Any]] = []
    for message in reversed(rest):
        candidate = [message, *kept]
        cost = _messages_cost(systems) + _messages_cost(candidate)
        if cost <= window_tokens or not kept:
            kept = candidate
        else:
            break

    kept = _repair_tool_chain(rest, kept)
    dropped = _suffix_dropped(rest, kept)

    if not dropped:
        return [*systems, *kept]

    if not summarize:
        # Repair may have pushed us slightly over budget; prefer a valid tool
        # chain over a strict token count when summarize is off.
        return [*systems, *kept]

    while True:
        summary = _summary_message(dropped)
        assembled = [*systems, summary, *kept]
        if _messages_cost(assembled) <= window_tokens or len(kept) <= 1:
            return assembled
        # Summary pushed us over budget: drop the oldest kept turn / tool round.
        # Orphan tool heads go into the summary rather than repairing upward
        # (which would fight the budget).
        kept = _drop_oldest_kept_turn(kept)
        dropped = _suffix_dropped(rest, kept)
        if not dropped:
            return [*systems, *kept]
