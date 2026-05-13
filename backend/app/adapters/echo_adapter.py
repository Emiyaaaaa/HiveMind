"""Echo adapter – useful for tests, demos and as a reference implementation.

It walks through a tiny three-step program and emits the same events any
real adapter would emit. There is no LLM call, no network IO, no extra deps.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.models.run import RunStatus


class EchoAdapter(OrchestratorAdapter):
    name = "echo"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        delay: float = float(ctx.agent_config.get("delay", 0.05))
        prompt: Any = ctx.input.get("prompt", "")

        await ctx.emit_step_started(index=0, node="plan")
        await ctx.emit_message(role="user", content=str(prompt))
        await asyncio.sleep(delay)
        await ctx.emit_step_completed(
            index=0, node="plan", output={"plan": ["greet", "respond"]}
        )

        await ctx.emit_step_started(index=1, node="tool")
        await ctx.emit_tool_call_started(
            step_index=1, name="echo", arguments={"text": prompt}
        )
        await asyncio.sleep(delay)
        await ctx.emit_tool_call_completed(
            step_index=1, name="echo", result={"text": prompt}
        )
        await ctx.emit_step_completed(
            index=1, node="tool", output={"echo": prompt}
        )

        reply = f"echo: {prompt}"
        await ctx.emit_step_started(index=2, node="reply")
        await ctx.emit_message(role="assistant", content=reply)
        await ctx.emit_step_completed(
            index=2, node="reply", output={"reply": reply}
        )

        return AdapterResult(status=RunStatus.SUCCEEDED, output={"reply": reply})
