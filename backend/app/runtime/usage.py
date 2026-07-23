"""Run-level token and cost aggregation."""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel


class RunUsage(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int | None = None
    step_count: int = 0
    failed_step_count: int = 0
    tool_call_count: int = 0
    failed_tool_call_count: int = 0


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


def _step_status(step: Any) -> str | None:
    value = getattr(step, "status", None)
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _step_tool_calls(step: Any) -> Iterable[Any]:
    calls = getattr(step, "tool_calls", None) or ()
    return calls


def aggregate_run_usage(steps: Iterable[Any]) -> RunUsage:
    """Sum metrics across all steps for a run."""
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    latency_sum = 0
    has_latency = False
    step_count = 0
    failed_step_count = 0
    tool_call_count = 0
    failed_tool_call_count = 0

    for step in steps:
        step_count += 1
        tokens_in += _step_tokens_in(step)
        tokens_out += _step_tokens_out(step)
        cost_usd += _step_cost_usd(step)
        latency = _step_latency_ms(step)
        if latency is not None:
            latency_sum += latency
            has_latency = True
        status = _step_status(step)
        if status == "failed":
            failed_step_count += 1
        for call in _step_tool_calls(step):
            tool_call_count += 1
            if getattr(call, "error", None):
                failed_tool_call_count += 1

    return RunUsage(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=round(cost_usd, 6),
        latency_ms=latency_sum if has_latency else None,
        step_count=step_count,
        failed_step_count=failed_step_count,
        tool_call_count=tool_call_count,
        failed_tool_call_count=failed_tool_call_count,
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
