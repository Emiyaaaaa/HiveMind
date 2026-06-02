"""Model pricing for cost estimation (USD per 1M tokens)."""

from __future__ import annotations

# OpenAI list prices (2026-05); unknown models fall back to gpt-4o-mini.
_MODEL_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "echo": {"input": 0.0, "output": 0.0},
}


def _normalize_model(model: str) -> str:
    name = (model or "").strip().lower()
    if "/" in name:
        name = name.split("/", 1)[1]
    return name


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate step/run cost from token counts and a model id."""
    key = _normalize_model(model)
    rates = _MODEL_PRICING_PER_1M.get(key)
    if rates is None:
        for candidate, table in _MODEL_PRICING_PER_1M.items():
            if key.startswith(candidate):
                rates = table
                break
    if rates is None:
        rates = _MODEL_PRICING_PER_1M["gpt-4o-mini"]
    cost = (tokens_in * rates["input"] + tokens_out * rates["output"]) / 1_000_000
    return round(cost, 6)
