"""Run-level token and cost aggregation."""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel, Field


class RunUsage(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int | None = None


def _step_tokens_in(step: Any) -> int:
    value = getattr(step, "tokens_in", None)
    return int(value) if value is not None else 0


def _step_tokens_out(step: Any) -> int:
    value = getattr(step, "tokens_out", None)
    return int(value) if value is not None else 0


def _step_cost_usd(step: Any) -> float:
    value = getattr(step, "cost_usd", None)
    return float(value) if value is not None else 0.0


def _step_latency_ms(step: Any) -> int | None:
    value = getattr(step, "latency_ms", None)
    return int(value) if value is not None else None


def aggregate_run_usage(steps: Iterable[Any]) -> RunUsage:
    """Sum metrics across all steps for a run."""
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    latency_sum = 0
    has_latency = False

    for step in steps:
        tokens_in += _step_tokens_in(step)
        tokens_out += _step_tokens_out(step)
        cost_usd += _step_cost_usd(step)
        latency = _step_latency_ms(step)
        if latency is not None:
            latency_sum += latency
            has_latency = True

    return RunUsage(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=round(cost_usd, 6),
        latency_ms=latency_sum if has_latency else None,
    )


def usage_from_metadata(metadata: dict[str, Any] | None) -> RunUsage | None:
    if not metadata:
        return None
    raw = metadata.get("usage")
    if not isinstance(raw, dict):
        return None
    try:
        return RunUsage.model_validate(raw)
    except Exception:
        return None
