"""Working-memory volume helpers and in-process threshold alerts."""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.runtime.memory_window import _messages_cost
from app.runtime.tokens import estimate_tokens

logger = get_logger("memory.metrics")

# Edge-trigger one alert per (run_id, kind) until the run clears or value drops.
_active_alerts: set[tuple[str, str]] = set()


def checkpoint_state_bytes(state: dict[str, Any]) -> int:
    """UTF-8 byte length of serialized checkpoint JSON."""
    return len(json.dumps(state, default=str, separators=(",", ":")).encode("utf-8"))


def estimate_prompt_tokens_from_history(messages: list[dict[str, Any]]) -> int:
    """Tokens in prior turns (all non-system messages except the latest one)."""
    non_system = [m for m in messages if m.get("role") != "system"]
    if len(non_system) <= 1:
        return 0
    return _messages_cost(non_system[:-1])


def clear_memory_alerts(run_id: str) -> None:
    """Drop edge-trigger state when a run reaches a terminal status."""
    to_remove = [key for key in _active_alerts if key[0] == run_id]
    for key in to_remove:
        _active_alerts.discard(key)


def maybe_alert_checkpoint_bytes(
    *,
    run_id: str,
    adapter: str,
    checkpoint_bytes: int,
) -> None:
    threshold = get_settings().memory_checkpoint_bytes_alert_threshold
    _maybe_alert(
        run_id=run_id,
        kind="checkpoint_bytes",
        value=checkpoint_bytes,
        threshold=threshold,
        adapter=adapter,
    )


def maybe_alert_messages_per_run(
    *,
    run_id: str,
    adapter: str,
    message_count: int,
) -> None:
    threshold = get_settings().memory_messages_per_run_alert_threshold
    _maybe_alert(
        run_id=run_id,
        kind="messages_per_run",
        value=message_count,
        threshold=threshold,
        adapter=adapter,
    )


def maybe_alert_prompt_tokens_from_history(
    *,
    run_id: str,
    adapter: str,
    tokens: int,
    step_index: int | None = None,
) -> None:
    threshold = get_settings().memory_prompt_tokens_from_history_alert_threshold
    _maybe_alert(
        run_id=run_id,
        kind="prompt_tokens_from_history",
        value=tokens,
        threshold=threshold,
        adapter=adapter,
        step_index=step_index,
    )


def _maybe_alert(
    *,
    run_id: str,
    kind: str,
    value: int,
    threshold: int,
    **extra: Any,
) -> None:
    key = (run_id, kind)
    if value < threshold:
        if key in _active_alerts:
            _active_alerts.discard(key)
            logger.info(
                f"memory.{kind}_alert.resolved",
                run_id=run_id,
                value=value,
                threshold=threshold,
                **extra,
            )
        return
    if key in _active_alerts:
        return
    _active_alerts.add(key)
    logger.warning(
        f"memory.{kind}_alert",
        run_id=run_id,
        value=value,
        threshold=threshold,
        **extra,
    )
