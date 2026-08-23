"""Run an existing PydanticAI agent on AgentFlow's adapter surface."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import AsyncExitStack
from importlib import import_module
from typing import Any

from app.adapters.adapter_tools import open_tool_surface
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.core.logging import get_logger
from app.models.run import RunStatus
from pydantic_ai import (
    Agent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ToolReturnPart,
)
from pydantic_core import to_jsonable_python

from agentflow_pydantic_ai.toolset import AgentFlowToolset

logger = get_logger("adapter.pydantic_ai")

DEFAULT_NODE = "pydantic_ai"


class PydanticAIAdapter(OrchestratorAdapter):
    """Load a trusted Agent factory and translate one run into one step."""

    name = "pydantic-ai"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        step_index = ctx.step_index_base
        node = str(ctx.agent_config.get("node") or DEFAULT_NODE)
        prompt = prompt_from_input(ctx.input)
        active_tools: dict[str, tuple[str, str, float]] = {}
        bridged_tool_calls: set[str] = set()

        await ctx.emit_step_started(index=step_index, node=node)
        await ctx.emit_message(role="user", content=prompt)
        started = time.monotonic()

        try:
            agent = load_agent(ctx.agent_config.get("agent_factory"))
            async with AsyncExitStack() as stack:
                bridge: AgentFlowToolset | None = None
                if uses_agentflow_tools(ctx.agent_config):
                    surface = await stack.enter_async_context(open_tool_surface(ctx.agent_config))
                    if surface.tools:
                        bridge = AgentFlowToolset(surface, ctx, step_index)

                async with agent.run_stream_events(
                    prompt,
                    run_id=ctx.run_id,
                    metadata=dict(ctx.metadata) or None,
                    toolsets=[bridge] if bridge is not None else None,
                ) as events:
                    async for event in events:
                        if delta := text_delta(event):
                            await ctx.emit_token_delta(step_index=step_index, delta=delta)
                        elif isinstance(event, FunctionToolCallEvent):
                            if bridge is not None and bridge.owns(event.part.tool_name):
                                bridged_tool_calls.add(event.tool_call_id)
                                continue
                            call_id = await ctx.emit_tool_call_started(
                                step_index=step_index,
                                name=event.part.tool_name,
                                arguments=event.part.args_as_dict(),
                            )
                            active_tools[event.tool_call_id] = (
                                event.part.tool_name,
                                call_id,
                                time.monotonic(),
                            )
                        elif isinstance(event, FunctionToolResultEvent):
                            if event.tool_call_id in bridged_tool_calls or (
                                bridge is not None and bridge.owns(event.part.tool_name)
                            ):
                                bridged_tool_calls.discard(event.tool_call_id)
                                continue
                            await emit_tool_result(ctx, step_index, event, active_tools)
                    result = events.result

            if result is None:
                raise RuntimeError("PydanticAI run ended without a final result")

            output = adapter_output(result.output)
            usage = result.usage
            metrics: dict[str, Any] = {
                "tokens_in": int(usage.input_tokens),
                "tokens_out": int(usage.output_tokens),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "requests": int(usage.requests),
            }
            if usage.cost is not None:
                metrics["cost_usd"] = float(usage.cost)

            await ctx.emit_message(role="assistant", content=output["reply"])
            await ctx.emit_step_completed(
                index=step_index,
                node=node,
                output=output,
                **metrics,
            )
            return AdapterResult(status=RunStatus.SUCCEEDED, output=output)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("pydantic_ai_run_failed", run_id=ctx.run_id)
            error = str(exc) or type(exc).__name__
            await close_active_tools(ctx, step_index, active_tools, error)
            await ctx.emit_step_failed(index=step_index, node=node, error=error)
            return AdapterResult(status=RunStatus.FAILED, error=error)


def uses_agentflow_tools(config: dict[str, Any]) -> bool:
    """Return whether this run asks AgentFlow to inject managed tools."""
    return bool(config.get("tools") or config.get("mcp_auto_register"))


def load_agent(reference: Any) -> Agent[Any, Any]:
    """Load ``module:factory`` from trusted worker code and create an Agent."""
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("agent_factory must be a non-empty 'module:factory' string")

    module_name, separator, factory_name = reference.strip().partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("agent_factory must use the 'module:factory' format")

    factory = getattr(import_module(module_name), factory_name, None)
    if not callable(factory):
        raise TypeError(f"agent_factory {reference!r} is not callable")

    agent = factory()
    if not isinstance(agent, Agent):
        raise TypeError(f"agent_factory {reference!r} must return pydantic_ai.Agent")
    return agent


async def emit_tool_result(
    ctx: AdapterContext,
    step_index: int,
    event: FunctionToolResultEvent,
    active_tools: dict[str, tuple[str, str, float]],
) -> None:
    """Pair provider tool IDs locally while persisting AgentFlow-owned ULIDs."""
    provider_id = event.tool_call_id
    active = active_tools.pop(provider_id, None)
    name = event.part.tool_name or (active[0] if active else "unknown")
    if active is None:
        call_id = await ctx.emit_tool_call_started(
            step_index=step_index,
            name=name,
            arguments={},
        )
        tool_started = time.monotonic()
    else:
        _, call_id, tool_started = active

    result, error = tool_result(event.part)
    await ctx.emit_tool_call_completed(
        step_index=step_index,
        name=name,
        call_id=call_id,
        result=result,
        error=error,
        latency_ms=int((time.monotonic() - tool_started) * 1000),
    )


async def close_active_tools(
    ctx: AdapterContext,
    step_index: int,
    active_tools: dict[str, tuple[str, str, float]],
    error: str,
) -> None:
    for name, call_id, tool_started in active_tools.values():
        await ctx.emit_tool_call_completed(
            step_index=step_index,
            name=name,
            call_id=call_id,
            error=error,
            latency_ms=int((time.monotonic() - tool_started) * 1000),
        )


def tool_result(part: ToolReturnPart | RetryPromptPart) -> tuple[dict[str, Any], str | None]:
    value = to_jsonable_python(part.content, fallback=str)
    result = value if isinstance(value, dict) else {"result": value}
    if isinstance(part, RetryPromptPart):
        return result, part.model_response()
    if part.outcome != "success":
        return result, part.model_response_str(wrap_if_error=False)
    return result, None


def text_delta(event: Any) -> str | None:
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta
    return None


def prompt_from_input(run_input: dict[str, Any]) -> str:
    for key in ("prompt", "message", "text", "input"):
        if key in run_input:
            value = run_input[key]
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return json.dumps(run_input, ensure_ascii=False)


def adapter_output(value: Any) -> dict[str, Any]:
    normalized = to_jsonable_python(value, fallback=str)
    if isinstance(normalized, str):
        return {"reply": normalized}
    reply = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return {"reply": reply, "structured_output": normalized}
