from app.runtime.pricing import estimate_cost_usd
from app.runtime.usage import RunUsage, aggregate_run_usage


def test_estimate_cost_usd_known_model():
    cost = estimate_cost_usd("openai/gpt-4o-mini", 1000, 500)
    assert cost == round((1000 * 0.15 + 500 * 0.60) / 1_000_000, 6)


def test_aggregate_run_usage_sums_steps():
    class Step:
        def __init__(self, **kwargs):
            self.tokens_in = kwargs.get("tokens_in")
            self.tokens_out = kwargs.get("tokens_out")
            self.cost_usd = kwargs.get("cost_usd")
            self.latency_ms = kwargs.get("latency_ms")

    usage = aggregate_run_usage(
        [
            Step(tokens_in=10, tokens_out=20, cost_usd=0.001, latency_ms=100),
            Step(tokens_in=5, tokens_out=15, cost_usd=0.002, latency_ms=50),
        ]
    )
    assert usage == RunUsage(
        tokens_in=15,
        tokens_out=35,
        cost_usd=0.003,
        latency_ms=150,
    )
