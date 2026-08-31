"""Run an existing AutoGen agent or team on AgentFlow's adapter surface."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import AsyncExitStack
from importlib import import_module
from inspect import signature
from typing import Any

from app.adapters.adapter_tools import open_tool_surface
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.core.logging import get_logger
from app.models.run import RunStatus
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import (
    BaseChatMessage,
    ModelClientStreamingChunkEvent,
    TextMessage,
    ToolCallExecutionEvent,
    ToolCallRequestEvent,
)

from agentflow_autogen.tools import (
    build_function_tools,
    inject_tools,
)

logger = get_logger("adapter.autogen")

DEFAULT_NODE = "autogen"
USER_SOURCE = "user"


class AutoGenAdapter(OrchestratorAdapter):
    """Load a trusted AutoGen agent/team factory and translate one run."""

    name = "autogen"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        config = ctx.agent_config
        default_node = str(config.get("node") or DEFAULT_NODE)
        prompt = prompt_from_input(ctx.input)
        team_mode = bool(config.get("team_factory"))
        per_turn_steps = bool(config.get("per_turn_steps", team_mode))
        stream_tokens = bool(config.get("stream_tokens", True))
        defer_initial_step = team_mode and per_turn_steps

        handler = _StreamHandler(
            ctx=ctx,
            default_node=default_node,
            per_turn_steps=per_turn_steps,
            stream_tokens=stream_tokens,
            step_index_base=ctx.step_index_base,
        )
        bridged_failure: list[str] = []

        try:
            async with AsyncExitStack() as stack:
                bridged_names: frozenset[str] = frozenset()
                if uses_agentflow_tools(config):
                    surface = await stack.enter_async_context(open_tool_surface(config))
                    if surface.tools:
                        if not defer_initial_step:
                            await handler.begin_step(default_node)
                        bridged_tools, bridged_names = build_function_tools(
                            surface,
                            ctx,
                            step_index=handler.current_step_index,
                            on_tool_error=bridged_failure.append,
                        )
                    else:
                        bridged_tools = []
                else:
                    bridged_tools = []

                runnable = load_runnable(config, bridged_tools=bridged_tools)
                maybe_enable_streaming(runnable, stream_tokens)

                if not handler.step_started and not defer_initial_step:
                    await handler.begin_step(default_node)

                await handler.emit_user_prompt(prompt)
                async for event in runnable.run_stream(task=prompt):
                    await handler.handle(event, bridged_names=bridged_names)

                if bridged_failure:
                    raise RuntimeError(bridged_failure[0])

                if handler.step_started and not handler.step_completed:
                    await handler.complete_step(output=handler.final_output())

            return AdapterResult(
                status=RunStatus.SUCCEEDED,
                output=handler.run_output(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("autogen_run_failed", run_id=ctx.run_id)
            error = str(exc) or type(exc).__name__
            await handler.fail_step(error)
            return AdapterResult(status=RunStatus.FAILED, error=error)


class _StreamHandler:
    """Translate AutoGen stream events into AgentFlow adapter events."""

    def __init__(
        self,
        *,
        ctx: AdapterContext,
        default_node: str,
        per_turn_steps: bool,
        stream_tokens: bool,
        step_index_base: int,
    ) -> None:
        self.ctx = ctx
        self.default_node = default_node
        self.per_turn_steps = per_turn_steps
        self.stream_tokens = stream_tokens
        self._next_step_index = step_index_base
        self._current_step_index = step_index_base
        self._current_node = default_node
        self.step_started = False
        self.step_completed = False
        self._started_at = 0.0
        self._tokens_in = 0
        self._tokens_out = 0
        self._final_reply = ""
        self._replies: list[str] = []
        self._active_tool_calls: dict[str, tuple[str, str, float]] = {}
        self._pending_user_prompt: str | None = None

    @property
    def current_step_index(self) -> int:
        return self._current_step_index

    async def begin_step(self, node: str) -> None:
        if self.step_started and not self.step_completed:
            return
        self._current_node = node
        self._current_step_index = self._next_step_index
        self._next_step_index += 1
        self.step_started = True
        self.step_completed = False
        self._started_at = time.monotonic()
        self._tokens_in = 0
        self._tokens_out = 0
        await self.ctx.emit_step_started(index=self._current_step_index, node=self._current_node)

    async def emit_user_prompt(self, prompt: str) -> None:
        self._pending_user_prompt = prompt
        await self.ctx.emit_message(role="user", content=prompt)

    async def handle(self, event: Any, *, bridged_names: frozenset[str]) -> None:
        if isinstance(event, ModelClientStreamingChunkEvent):
            if self.stream_tokens and isinstance(event.content, str):
                await self.ctx.emit_token_delta(
                    step_index=self._current_step_index,
                    delta=event.content,
                )
            return

        if isinstance(event, TextMessage):
            await self._handle_text_message(event)
            return

        if isinstance(event, ToolCallRequestEvent):
            await self._handle_tool_request(event, bridged_names=bridged_names)
            return

        if isinstance(event, ToolCallExecutionEvent):
            await self._handle_tool_execution(event, bridged_names=bridged_names)
            return

        if isinstance(event, TaskResult):
            await self._handle_task_result(event)

    async def _handle_text_message(self, message: TextMessage) -> None:
        if message.source == USER_SOURCE:
            content = str(message.content or "")
            if self._pending_user_prompt is not None and content == self._pending_user_prompt:
                self._pending_user_prompt = None
                return
            await self.ctx.emit_message(role="user", content=content, name=message.source)
            return

        if self.per_turn_steps:
            if self.step_started and not self.step_completed:
                await self.complete_step(output={"reply": self._final_reply})
            await self.begin_step(str(message.source or self.default_node))

        if not self.step_started:
            await self.begin_step(str(message.source or self.default_node))

        self._accumulate_usage(message)
        content = str(message.content or "")
        if content:
            self._final_reply = content
            self._replies.append(content)
            await self.ctx.emit_message(
                role="assistant",
                content=content,
                name=message.source,
            )

    async def _handle_tool_request(
        self,
        event: ToolCallRequestEvent,
        *,
        bridged_names: frozenset[str],
    ) -> None:
        self._accumulate_usage(event)
        for call in event.content:
            if call.name in bridged_names:
                continue
            arguments = _parse_tool_arguments(call.arguments)
            call_id = await self.ctx.emit_tool_call_started(
                step_index=self._current_step_index,
                name=call.name,
                arguments=arguments,
            )
            self._active_tool_calls[call.id] = (call.name, call_id, time.monotonic())

    async def _handle_tool_execution(
        self,
        event: ToolCallExecutionEvent,
        *,
        bridged_names: frozenset[str],
    ) -> None:
        for result in event.content:
            if result.name in bridged_names:
                continue
            active = self._active_tool_calls.pop(result.call_id, None)
            if active is None:
                call_id = await self.ctx.emit_tool_call_started(
                    step_index=self._current_step_index,
                    name=result.name,
                    arguments={},
                )
                started = time.monotonic()
            else:
                _, call_id, started = active
            payload = {"result": result.content}
            await self.ctx.emit_tool_call_completed(
                step_index=self._current_step_index,
                name=result.name,
                call_id=call_id,
                result=payload,
                error=str(result.content) if result.is_error else None,
                latency_ms=int((time.monotonic() - started) * 1000),
            )

    async def _handle_task_result(self, result: TaskResult) -> None:
        for message in result.messages:
            if isinstance(message, TextMessage) and message.source != USER_SOURCE:
                self._accumulate_usage(message)
                content = str(message.content or "")
                if content:
                    self._final_reply = content
                    if content not in self._replies:
                        self._replies.append(content)

    def _accumulate_usage(self, message: Any) -> None:
        usage = getattr(message, "models_usage", None)
        if usage is None:
            return
        self._tokens_in += int(getattr(usage, "prompt_tokens", 0) or 0)
        self._tokens_out += int(getattr(usage, "completion_tokens", 0) or 0)

    async def complete_step(self, *, output: dict[str, Any]) -> None:
        if not self.step_started or self.step_completed:
            return
        latency_ms = int((time.monotonic() - self._started_at) * 1000)
        metrics: dict[str, Any] = {
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
            "latency_ms": latency_ms,
        }
        await self.ctx.emit_step_updated(index=self._current_step_index, **metrics)
        await self.ctx.emit_step_completed(
            index=self._current_step_index,
            node=self._current_node,
            output=output,
            **metrics,
        )
        self.step_completed = True

    async def fail_step(self, error: str) -> None:
        if not self.step_started:
            await self.ctx.emit_step_started(index=self._current_step_index, node=self._current_node)
        await self._close_active_tools(error)
        await self.ctx.emit_step_failed(
            index=self._current_step_index,
            node=self._current_node,
            error=error,
        )

    async def _close_active_tools(self, error: str) -> None:
        for name, call_id, started in self._active_tool_calls.values():
            await self.ctx.emit_tool_call_completed(
                step_index=self._current_step_index,
                name=name,
                call_id=call_id,
                error=error,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        self._active_tool_calls.clear()

    def final_output(self) -> dict[str, Any]:
        reply = self._final_reply or (self._replies[-1] if self._replies else "")
        output: dict[str, Any] = {"reply": reply}
        if len(self._replies) > 1:
            output["replies"] = list(self._replies)
        return output

    def run_output(self) -> dict[str, Any]:
        return self.final_output()


def uses_agentflow_tools(config: dict[str, Any]) -> bool:
    return bool(config.get("tools") or config.get("mcp_auto_register"))


def load_runnable(config: dict[str, Any], *, bridged_tools: list[Any]) -> Any:
    """Load an AutoGen agent or team from trusted worker code."""
    if config.get("team_factory"):
        runnable = _load_factory(config["team_factory"], bridged_tools=bridged_tools)
        if not hasattr(runnable, "run_stream"):
            raise TypeError("team_factory must return an object with run_stream()")
        return runnable

    if config.get("agent_factory"):
        agent = _load_factory(config["agent_factory"], bridged_tools=bridged_tools)
        if not hasattr(agent, "run_stream"):
            raise TypeError("agent_factory must return an object with run_stream()")
        return inject_tools(agent, bridged_tools)

    raise ValueError("agent_factory or team_factory must be configured")


def _load_factory(reference: Any, *, bridged_tools: list[Any]) -> Any:
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("factory must be a non-empty 'module:factory' string")

    module_name, separator, factory_name = reference.strip().partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("factory must use the 'module:factory' format")

    factory = getattr(import_module(module_name), factory_name, None)
    if not callable(factory):
        raise TypeError(f"factory {reference!r} is not callable")

    kwargs: dict[str, Any] = {}
    params = signature(factory).parameters
    if bridged_tools and "agentflow_tools" in params:
        kwargs["agentflow_tools"] = bridged_tools

    return factory(**kwargs)


def maybe_enable_streaming(runnable: Any, stream_tokens: bool) -> None:
    if not stream_tokens:
        return
    stream_attr = getattr(runnable, "_model_client_stream", None)
    if isinstance(stream_attr, bool):
        runnable._model_client_stream = True


def prompt_from_input(run_input: dict[str, Any]) -> str:
    for key in ("prompt", "message", "text", "input", "task"):
        if key in run_input:
            value = run_input[key]
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return json.dumps(run_input, ensure_ascii=False)


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": raw}
