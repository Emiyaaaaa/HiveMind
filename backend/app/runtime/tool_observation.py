"""Bounded, structure-aware observations for tool results.

ToolCall persistence keeps the complete result for auditability, while the
model receives a bounded JSON observation. This module deliberately performs
deterministic previewing; semantic summarization belongs to a later policy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.runtime.tokens import estimate_tokens

MIN_OBSERVATION_TOKENS = 32
DEFAULT_OBSERVATION_TOKENS = 0
_PRIORITY_KEYS = ("ok", "status", "error", "code", "message", "id", "name", "type")


@dataclass(frozen=True)
class ToolObservationConfig:
    """Per-run budget for serialized tool observations; zero disables previewing."""

    max_tokens: int = DEFAULT_OBSERVATION_TOKENS

    @property
    def enabled(self) -> bool:
        return self.max_tokens > 0


@dataclass
class _PreviewStats:
    omitted_items: int = 0


def parse_tool_observation_config(config: Mapping[str, Any]) -> ToolObservationConfig:
    """Parse the optional ``tool_observation.max_tokens`` agent setting."""
    raw = config.get("tool_observation")
    if raw is None:
        return ToolObservationConfig()
    if not isinstance(raw, Mapping):
        raise ValueError("tool_observation must be an object")

    value = raw.get("max_tokens", DEFAULT_OBSERVATION_TOKENS)
    if isinstance(value, bool):
        raise ValueError("tool_observation.max_tokens must be an integer")
    try:
        max_tokens = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("tool_observation.max_tokens must be an integer") from exc
    if max_tokens < 0:
        raise ValueError("tool_observation.max_tokens must be zero or greater")
    if 0 < max_tokens < MIN_OBSERVATION_TOKENS:
        raise ValueError(
            f"tool_observation.max_tokens must be zero or at least {MIN_OBSERVATION_TOKENS}"
        )
    return ToolObservationConfig(max_tokens=max_tokens)


def serialize_tool_observation(value: Any, *, max_tokens: int) -> str:
    """Serialize a tool result without exceeding the configured token budget.

    Small results are returned unchanged. Large mappings and sequences are
    previewed in their original order, with operational fields considered
    first. The returned value is always valid JSON and includes truncation
    metadata when a preview was required.
    """
    full = _json(value)
    original_tokens = estimate_tokens(full)
    if max_tokens <= 0 or original_tokens <= max_tokens:
        return full

    stats = _PreviewStats()
    target_chars = max_tokens * 4
    preview = value
    text = ""
    for _ in range(12):
        stats.omitted_items = 0
        preview = _preview(value, target_chars, stats)
        metadata = {
            "truncated": True,
            "original_tokens": original_tokens,
            "visible_tokens": estimate_tokens(_json(preview)),
            "omitted_items": stats.omitted_items,
        }
        if isinstance(preview, dict):
            envelope = {**preview, "_observation": metadata}
        else:
            envelope = {"_observation": metadata, "data": preview}
        text = _json(envelope)
        if estimate_tokens(text) <= max_tokens:
            return text
        target_chars = max(32, int(target_chars * 0.75))

    # The minimum configured budget leaves room for this compact valid JSON
    # fallback even when the input is an unusual scalar or deeply nested value.
    fallback = {
        "_observation": {
            "truncated": True,
            "original_tokens": original_tokens,
            "visible_tokens": 1,
            "omitted_items": 1,
        },
        "data": "[tool result omitted]",
    }
    text = _json(fallback)
    if estimate_tokens(text) <= max_tokens:
        return text
    return _json({"_observation": {"truncated": True}, "data": ""})


def _preview(value: Any, budget_chars: int, stats: _PreviewStats) -> Any:
    if budget_chars <= 8:
        stats.omitted_items += 1
        return "..."
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _preview_string(value, budget_chars, stats)
    if isinstance(value, Mapping):
        return _preview_mapping(value, budget_chars, stats)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return _preview_sequence(value, budget_chars, stats)
    return _preview_string(str(value), budget_chars, stats)


def _preview_string(value: str, budget_chars: int, stats: _PreviewStats) -> str:
    if len(_json(value)) <= budget_chars:
        return value
    stats.omitted_items += 1
    marker = "...[truncated]"
    available = max(1, budget_chars - len(_json(marker)))
    left = max(1, available // 2)
    right = max(0, available - left)
    return value[:left] + marker + (value[-right:] if right else "")


def _preview_mapping(
    value: Mapping[Any, Any], budget_chars: int, stats: _PreviewStats
) -> dict[str, Any]:
    items = list(enumerate(value.items()))
    priority = {key: index for index, key in enumerate(_PRIORITY_KEYS)}
    items.sort(key=lambda item: (priority.get(str(item[1][0]), len(priority)), item[0]))
    result: dict[str, Any] = {}
    for _, (key, item) in items:
        name = str(key)
        current = len(_json(result))
        key_cost = len(_json(name)) + 3
        child_budget = max(8, budget_chars - current - key_cost)
        child = _preview(item, child_budget, stats)
        candidate = {**result, name: child}
        if len(_json(candidate)) <= budget_chars:
            result[name] = child
        else:
            stats.omitted_items += 1
    return result


def _preview_sequence(value: Sequence[Any], budget_chars: int, stats: _PreviewStats) -> list[Any]:
    result: list[Any] = []
    for item in value:
        current = len(_json(result))
        child_budget = max(8, budget_chars - current - 2)
        child = _preview(item, child_budget, stats)
        candidate = [*result, child]
        if len(_json(candidate)) <= budget_chars:
            result.append(child)
        else:
            stats.omitted_items += len(value) - len(result)
            break
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
