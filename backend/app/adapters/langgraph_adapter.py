"""LangGraph adapter – the default production adapter.

The adapter constructs a tiny `StateGraph` from the agent's config and
streams every node tick back to the runtime through `AdapterContext`.
LangGraph is imported lazily so the rest of AgentFlow does not pay the
import cost in tests that exercise only the echo adapter.

Expected agent.config shape (all optional):

```jsonc
{
  "model": "openai/gpt-4o-mini",
  "system_prompt": "You are a helpful coordinator.",
  "tools": []                 // tool registry keys, resolved by the runtime
}
```

If `agent.config.graph` is provided it is treated as an opaque description
the adapter can specialise on. The MVP shipped here implements a
single-node graph that calls the model once; richer multi-node graphs can
be added behind the same interface without touching the runtime tables.
"""

from __future__ import annotations

from typing import Any

from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.run import RunStatus

logger = get_logger("adapter.langgraph")


class LangGraphAdapter(OrchestratorAdapter):
    name = "langgraph"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError:  # pragma: no cover - dep guard
            return AdapterResult(
                status=RunStatus.FAILED,
                error="langgraph is not installed; add it to your environment.",
            )

        config = ctx.agent_config
        system_prompt: str = config.get("system_prompt", "You are a helpful agent.")
        model: str = config.get("model", "openai/gpt-4o-mini")

        async def call_model(state: dict[str, Any]) -> dict[str, Any]:
            await ctx.emit_step_started(index=0, node="call_model")
            user_input = state.get("input", "")
            await ctx.emit_message(role="system", content=system_prompt)
            await ctx.emit_message(role="user", content=str(user_input))

            reply = await self._invoke_model(model, system_prompt, str(user_input))

            await ctx.emit_message(role="assistant", content=reply)
            await ctx.emit_step_completed(
                index=0, node="call_model", output={"reply": reply}
            )
            return {"reply": reply}

        graph = StateGraph(dict)
        graph.add_node("call_model", call_model)
        graph.add_edge(START, "call_model")
        graph.add_edge("call_model", END)
        compiled = graph.compile()

        try:
            final_state = await compiled.ainvoke({"input": ctx.input.get("prompt", "")})
        except Exception as exc:  # pragma: no cover - depends on external model
            logger.exception("langgraph_run_failed", run_id=ctx.run_id)
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))

        return AdapterResult(
            status=RunStatus.SUCCEEDED,
            output={"reply": final_state.get("reply")},
        )

    async def _invoke_model(self, model: str, system_prompt: str, user_input: str) -> str:
        """Call the configured chat model.

        The MVP routes everything through an OpenAI-compatible Chat
        Completions endpoint. Swap this method to use LiteLLM, Bedrock,
        Anthropic, etc. without touching the rest of the adapter.
        """
        settings = get_settings()
        if not settings.openai_api_key:
            return f"[mock:{model}] {user_input}"

        import httpx

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": model.split("/", 1)[-1],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_input},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
