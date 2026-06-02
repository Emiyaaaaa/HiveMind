"""Echo adapter – useful for tests, demos and as a reference implementation.

It walks through a tiny three-step program and emits the same events any
real adapter would emit. There is no LLM call, no network IO, no extra deps.

Agent config knobs for retry / resume demos:

- ``fail_at_node``: ``"tool"`` — fail on first attempt at the tool step;
  succeeds on ``retry`` when a checkpoint exists.
- ``pause_before_reply``: ``true`` — stop in ``waiting_human`` after the tool
  step; ``resume`` continues from the saved checkpoint.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.models.run import RunStatus
from app.runtime.pricing import estimate_cost_usd
from app.runtime.tokens import estimate_tokens
_STEPS = ("plan", "tool", "reply")


def _start_step_index(ctx: AdapterContext) -> int:
    if ctx.resume and ctx.resume.checkpoint_state:
        raw = ctx.resume.checkpoint_state.get("next_step_index", 0)
        try:
            return max(0, min(int(raw), len(_STEPS) - 1))
        except (TypeError, ValueError):
            return 0
    return 0


def _step_index(ctx: AdapterContext, logical: int, start_logical: int) -> int:
    return ctx.step_index_base + (logical - start_logical)


async def _checkpoint_after(ctx: AdapterContext, next_step_index: int) -> None:
    await ctx.emit_checkpoint(
        label=_STEPS[next_step_index - 1] if next_step_index > 0 else "start",
        state={"next_step_index": next_step_index},
    )


class EchoAdapter(OrchestratorAdapter):
    name = "echo"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        delay: float = float(ctx.agent_config.get("delay", 0.05))
        prompt: Any = ctx.input.get("prompt", "")
        fail_at: str | None = ctx.agent_config.get("fail_at_node")
        pause_before_reply = bool(ctx.agent_config.get("pause_before_reply"))
        start = _start_step_index(ctx)
        is_retry = ctx.resume is not None and ctx.resume.mode == "retry"

        if start <= 0:
            idx = _step_index(ctx, 0, start)
            await ctx.emit_step_started(index=idx, node="plan")
            await ctx.emit_message(role="user", content=str(prompt))
            await asyncio.sleep(delay)
            await ctx.emit_step_completed(
                index=idx, node="plan", output={"plan": ["greet", "respond"]}
            )
            await _checkpoint_after(ctx, 1)

        if start <= 1:
            idx = _step_index(ctx, 1, start)
            if fail_at == "tool" and not is_retry:
                await ctx.emit_step_started(index=idx, node="tool")
                await ctx.emit_step_failed(
                    index=idx, node="tool", error="simulated tool failure"
                )
                return AdapterResult(
                    status=RunStatus.FAILED,
                    error="simulated tool failure",
                )

            await ctx.emit_step_started(index=idx, node="tool")
            await ctx.emit_tool_call_started(
                step_index=idx, name="echo", arguments={"text": prompt}
            )
            await asyncio.sleep(delay)
            await ctx.emit_tool_call_completed(
                step_index=idx, name="echo", result={"text": prompt}
            )
            await ctx.emit_step_completed(
                index=idx, node="tool", output={"echo": prompt}
            )
            await _checkpoint_after(ctx, 2)

            if pause_before_reply and not (
                ctx.resume and ctx.resume.mode == "resume"
            ):
                return AdapterResult(
                    status=RunStatus.WAITING_HUMAN,
                    output={"awaiting": "human approval before reply"},
                )

        reply = f"echo: {prompt}"
        if ctx.resume and ctx.resume.mode == "resume" and ctx.resume.human_input:
            approval = ctx.resume.human_input.get("approval", "")
            if approval:
                reply = f"{reply} ({approval})"

        idx = _step_index(ctx, 2, start)
        model = str(ctx.agent_config.get("model", "echo"))
        tokens_in = estimate_tokens(str(prompt))
        tokens_out = estimate_tokens(reply)
        cost_usd = estimate_cost_usd(model, tokens_in, tokens_out)
        await ctx.emit_step_started(index=idx, node="reply")
        await ctx.emit_message(role="assistant", content=reply)
        await ctx.emit_step_updated(
            index=idx,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )
        await ctx.emit_step_completed(
            index=idx,
            node="reply",
            output={"reply": reply},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

        return AdapterResult(status=RunStatus.SUCCEEDED, output={"reply": reply})
