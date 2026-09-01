"""Resume / retry metadata passed from the API into the worker executor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RESUME_META_KEY = "_resume"


@dataclass(frozen=True)
class RunResumeContext:
    """Adapter-facing resume instructions for a single execution attempt.

    ``checkpoint_state`` is hydrated by the worker from the checkpoints table;
    it is not serialized into ``Run.metadata`` (only ``checkpoint_index`` is).
    """

    mode: Literal["retry", "resume"]
    checkpoint_state: dict[str, Any] | None = None
    checkpoint_index: int | None = None
    human_input: dict[str, Any] | None = None


def resume_metadata(
    *,
    mode: Literal["retry", "resume"],
    checkpoint_index: int | None = None,
    human_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the small ``_resume`` block stored on ``Run.metadata``."""
    payload: dict[str, Any] = {"mode": mode}
    if checkpoint_index is not None:
        payload["checkpoint_index"] = checkpoint_index
    if human_input is not None:
        payload["human_input"] = human_input
    return {RESUME_META_KEY: payload}


def parse_resume_context(metadata: dict[str, Any] | None) -> RunResumeContext | None:
    if not metadata:
        return None
    raw = metadata.get(RESUME_META_KEY)
    if not isinstance(raw, dict):
        return None
    mode = raw.get("mode")
    if mode not in ("retry", "resume"):
        return None
    human_input = raw.get("human_input")
    if human_input is not None and not isinstance(human_input, dict):
        human_input = None
    checkpoint_index = raw.get("checkpoint_index")
    if checkpoint_index is not None:
        try:
            checkpoint_index = int(checkpoint_index)
        except (TypeError, ValueError):
            checkpoint_index = None
    return RunResumeContext(
        mode=mode,
        checkpoint_index=checkpoint_index,
        human_input=human_input,
    )


def without_resume_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    if RESUME_META_KEY not in metadata:
        return metadata
    cleaned = dict(metadata)
    cleaned.pop(RESUME_META_KEY, None)
    return cleaned
