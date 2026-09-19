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


def _summarize_dropped(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role") or "?")
        content = str(message.get("content") or "")
        if not content and message.get("tool_calls"):
            names = [
                str(tc.get("name") or "")
                for tc in message.get("tool_calls") or []
            ]
            content = f"[tool_calls: {', '.join(n for n in names if n)}]"
        if content:
            parts.append(f"{role}: {content[:300]}")
    body = "\n".join(parts)
    if len(body) > 2000:
        body = body[:2000] + "..."
    return f"[Earlier conversation summary]\n{body}"


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


def _repair_tool_chain(
    rest: list[dict[str, Any]], kept: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ensure a leading tool message still has its assistant tool-call parent.

    Walks backward through ``rest`` while the window head is ``role=tool``,
    prepending the prior message so OpenAI-compatible tool protocols stay valid.
    """
    while kept and kept[0].get("role") == "tool":
        idx = len(rest) - len(kept) - 1
        if idx < 0:
            break
        kept = [rest[idx], *kept]
    return kept


def _drop_leading_orphan_tools(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When shrinking for budget, drop orphan tool heads instead of repairing up."""
    while kept and kept[0].get("role") == "tool":
        kept = kept[1:]
    return kept


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
        return [*systems, *kept]

    while True:
        summary = {"role": "system", "content": _summarize_dropped(dropped)}
        assembled = [*systems, summary, *kept]
        if _messages_cost(assembled) <= window_tokens or len(kept) <= 1:
            return assembled
        # Summary pushed us over budget: drop the oldest kept turn. If that
        # would leave an orphan tool head, drop those tools into the summary
        # rather than repairing upward (which would fight the budget).
        kept = _drop_leading_orphan_tools(kept[1:])
        dropped = _suffix_dropped(rest, kept)
        if not dropped:
            return [*systems, *kept]
