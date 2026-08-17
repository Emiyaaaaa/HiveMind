from __future__ import annotations

from typing import Any

import pytest
from app.adapters.base import AdapterContext
from app.models.run import RunStatus
from pydantic_ai import Agent
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

from agentflow_pydantic_ai import PydanticAIAdapter, create_adapter


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


def not_an_agent() -> object:
    return object()


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
async def test_invalid_factory_becomes_a_failed_step() -> None:
    ctx = RecordingContext(factory_reference("not_an_agent"))

    result = await PydanticAIAdapter().run(ctx)

    assert result.status == RunStatus.FAILED
    assert "must return pydantic_ai.Agent" in (result.error or "")
    assert ctx.event("step.failed")[0]["error"] == result.error
