from __future__ import annotations

from typing import Any

import pytest
from app.adapters.base import AdapterContext
from app.adapters.tool_registry import register_tool
from app.models.run import RunStatus
from pydantic_ai import Agent
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

from agentflow_pydantic_ai import PydanticAIAdapter, create_adapter
from agentflow_pydantic_ai.toolset import pydantic_tool_name


class RecordingContext(AdapterContext):
    def __init__(self, agent_factory: str) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        super().__init__(
            run_id="01PYDANTICAI",
            agent_id="01AGENT",
            agent_config={"agent_factory": agent_factory},
            input={"prompt": "hello"},
            emit=self._emit,
        )

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))

    def event(self, event_type: str) -> list[dict[str, Any]]:
        return [data for current, data in self.events if current == event_type]


def factory_reference(name: str) -> str:
    return f"{__name__}:{name}"


def text_agent() -> Agent[None, str]:
    return Agent(TestModel(custom_output_text="Hello from PydanticAI"))


def tool_agent() -> Agent[None, str]:
    requests = 0

    async def stream_model(_messages: list[Any], _info: Any):
        nonlocal requests
        requests += 1
        if requests == 1:
            yield {
                0: DeltaToolCall(
                    name="echo",
                    json_args='{"text":"ping"}',
                    tool_call_id="provider-call-id-that-is-not-a-ulid",
                )
            }
        else:
            yield "tool finished"

    agent = Agent(FunctionModel(stream_function=stream_model))

    @agent.tool_plain
    async def echo(text: str) -> dict[str, str]:
        return {"text": text}

    return agent


def bridged_tool_agent() -> Agent[None, str]:
    return Agent(TestModel(call_tools=["echo"]))


def mixed_tool_agent() -> Agent[None, str]:
    agent = Agent(TestModel(call_tools=["echo", "local_upper"]))

    @agent.tool_plain
    async def local_upper(text: str) -> dict[str, str]:
        return {"text": text.upper()}

    return agent


def failing_tool_agent() -> Agent[None, str]:
    return Agent(TestModel(call_tools=["bridge_failure"]))


def not_an_agent() -> object:
    return object()


def test_mcp_tool_names_are_provider_safe() -> None:
    assert pydantic_tool_name("mcp/knowledge/search") == "mcp__knowledge__search"
    assert len(pydantic_tool_name("mcp/" + "x" * 100)) == 64


@pytest.mark.asyncio
async def test_factory_run_streams_messages_and_usage() -> None:
    adapter = create_adapter()
    ctx = RecordingContext(factory_reference("text_agent"))

    result = await adapter.run(ctx)

    assert isinstance(adapter, PydanticAIAdapter)
    assert result.status == RunStatus.SUCCEEDED
    assert result.output == {"reply": "Hello from PydanticAI"}
    assert ctx.event("step.started") == [{"index": 0, "node": "pydantic_ai"}]
    assert "".join(item["delta"] for item in ctx.event("token.delta")) == ("Hello from PydanticAI")
    assert [item["role"] for item in ctx.event("message.created")] == [
        "user",
        "assistant",
    ]
    assert ctx.event("step.completed")[0]["tokens_in"] > 0
    assert ctx.event("step.completed")[0]["output"] == result.output


@pytest.mark.asyncio
async def test_native_tool_events_use_agentflow_ids() -> None:
    ctx = RecordingContext(factory_reference("tool_agent"))

    result = await PydanticAIAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    started = ctx.event("tool_call.started")[0]
    completed = ctx.event("tool_call.completed")[0]
    assert started["name"] == "echo"
    assert started["arguments"] == {"text": "ping"}
    assert len(started["call_id"]) == 26
    assert started["call_id"] != "provider-call-id-that-is-not-a-ulid"
    assert completed["call_id"] == started["call_id"]
    assert completed["result"] == {"text": "ping"}
    assert completed["error"] is None


@pytest.mark.asyncio
async def test_agentflow_builtin_tool_is_injected_without_duplicate_events() -> None:
    ctx = RecordingContext(factory_reference("bridged_tool_agent"))
    ctx.agent_config["tools"] = ["echo"]

    result = await PydanticAIAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    started = ctx.event("tool_call.started")
    completed = ctx.event("tool_call.completed")
    assert len(started) == len(completed) == 1
    assert started[0]["name"] == "echo"
    assert completed[0]["result"] == {"text": ""}
    assert completed[0]["call_id"] == started[0]["call_id"]


@pytest.mark.asyncio
async def test_agentflow_and_factory_tools_can_run_together() -> None:
    ctx = RecordingContext(factory_reference("mixed_tool_agent"))
    ctx.agent_config["tools"] = ["echo"]

    result = await PydanticAIAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    assert {event["name"] for event in ctx.event("tool_call.started")} == {
        "echo",
        "local_upper",
    }
    assert len(ctx.event("tool_call.completed")) == 2


@pytest.mark.asyncio
async def test_agentflow_tool_failure_is_emitted_once() -> None:
    async def fail(_arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("bridge exploded")

    register_tool("bridge_failure", fail, overwrite=True)
    ctx = RecordingContext(factory_reference("failing_tool_agent"))
    ctx.agent_config["tools"] = ["bridge_failure"]

    result = await PydanticAIAdapter().run(ctx)

    assert result.status == RunStatus.FAILED
    assert result.error == "bridge exploded"
    assert len(ctx.event("tool_call.started")) == 1
    assert len(ctx.event("tool_call.completed")) == 1
    assert ctx.event("tool_call.completed")[0]["error"] == "bridge exploded"


@pytest.mark.asyncio
async def test_invalid_factory_becomes_a_failed_step() -> None:
    ctx = RecordingContext(factory_reference("not_an_agent"))

    result = await PydanticAIAdapter().run(ctx)

    assert result.status == RunStatus.FAILED
    assert "must return pydantic_ai.Agent" in (result.error or "")
    assert ctx.event("step.failed")[0]["error"] == result.error
