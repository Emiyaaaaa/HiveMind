from __future__ import annotations

import json
from typing import Any

import pytest
from app.adapters.base import AdapterContext
from app.adapters.tool_registry import register_tool
from app.models.run import RunStatus
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core._types import FunctionCall
from autogen_core.models import CreateResult, ModelInfo, RequestUsage
from autogen_ext.models.replay import ReplayChatCompletionClient

from agentflow_autogen import AutoGenAdapter, create_adapter


class RecordingContext(AdapterContext):
    def __init__(self, config: dict[str, Any], *, prompt: str = "hello") -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        super().__init__(
            run_id="01AUTOGEN",
            agent_id="01AGENT",
            agent_config=config,
            input={"prompt": prompt},
            emit=self._emit,
        )

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))

    def event(self, event_type: str) -> list[dict[str, Any]]:
        return [data for current, data in self.events if current == event_type]


def factory_reference(name: str) -> str:
    return f"{__name__}:{name}"


def text_agent(*, agentflow_tools=None) -> AssistantAgent:
    client = ReplayChatCompletionClient(
        ["Hello from AutoGen"],
        model_info=ModelInfo(
            vision=False,
            function_calling=True,
            json_output=False,
            family="unknown",
        ),
    )
    tools = list(agentflow_tools or [])
    return AssistantAgent(
        name="assistant",
        model_client=client,
        tools=tools,
        model_client_stream=True,
    )


def tool_agent(*, agentflow_tools=None) -> AssistantAgent:
    async def echo(text: str) -> str:
        return f"echo:{text}"

    usage = RequestUsage(prompt_tokens=5, completion_tokens=2)
    call = FunctionCall(id="provider-call-id", name="echo", arguments=json.dumps({"text": "ping"}))
    responses = [
        CreateResult(content=[call], finish_reason="function_calls", usage=usage, cached=False),
        CreateResult(content="done", finish_reason="stop", usage=usage, cached=False),
    ]
    client = ReplayChatCompletionClient(
        responses,
        model_info=ModelInfo(
            vision=False,
            function_calling=True,
            json_output=False,
            family="unknown",
        ),
    )
    tools = [echo, *(agentflow_tools or [])]
    return AssistantAgent(
        name="assistant",
        model_client=client,
        tools=tools,
        reflect_on_tool_use=False,
    )


def bridged_tool_agent(*, agentflow_tools=None) -> AssistantAgent:
    usage = RequestUsage(prompt_tokens=5, completion_tokens=2)
    tool_name = "echo"
    if agentflow_tools:
        tool_name = getattr(agentflow_tools[0], "name", tool_name)
    call = FunctionCall(
        id="bridge-call",
        name=tool_name,
        arguments=json.dumps({"text": "ping"}),
    )
    responses = [
        CreateResult(content=[call], finish_reason="function_calls", usage=usage, cached=False),
        CreateResult(content="bridged", finish_reason="stop", usage=usage, cached=False),
    ]
    client = ReplayChatCompletionClient(
        responses,
        model_info=ModelInfo(
            vision=False,
            function_calling=True,
            json_output=False,
            family="unknown",
        ),
    )
    tools = list(agentflow_tools or [])
    return AssistantAgent(
        name="assistant",
        model_client=client,
        tools=tools,
        reflect_on_tool_use=False,
    )


def writer_agent() -> AssistantAgent:
    client = ReplayChatCompletionClient(["Writer says hi"])
    return AssistantAgent(name="writer", model_client=client)


def editor_agent() -> AssistantAgent:
    client = ReplayChatCompletionClient(["Editor approves"])
    return AssistantAgent(name="editor", model_client=client)


def create_team() -> RoundRobinGroupChat:
    return RoundRobinGroupChat([writer_agent(), editor_agent()], max_turns=2)


def bridged_team_agent(
    name: str,
    reply: str,
    *,
    agentflow_tools=None,
) -> AssistantAgent:
    usage = RequestUsage(prompt_tokens=5, completion_tokens=2)
    tools = list(agentflow_tools or [])
    tool_name = getattr(tools[0], "name", "echo") if tools else "echo"
    call = FunctionCall(
        id=f"{name}-bridge-call",
        name=tool_name,
        arguments=json.dumps({"text": name}),
    )
    client = ReplayChatCompletionClient(
        [
            CreateResult(content=[call], finish_reason="function_calls", usage=usage, cached=False),
            CreateResult(content=reply, finish_reason="stop", usage=usage, cached=False),
        ],
        model_info=ModelInfo(
            vision=False,
            function_calling=True,
            json_output=False,
            family="unknown",
        ),
    )
    return AssistantAgent(
        name=name,
        model_client=client,
        tools=tools,
        reflect_on_tool_use=True,
    )


def create_bridged_team(*, agentflow_tools=None) -> RoundRobinGroupChat:
    tools = list(agentflow_tools or [])
    return RoundRobinGroupChat(
        [
            bridged_team_agent("writer", "Writer used the bridge", agentflow_tools=tools),
            bridged_team_agent("editor", "Editor used the bridge", agentflow_tools=tools),
        ],
        max_turns=2,
    )


class RepeatedMessageTeam:
    async def run_stream(self, *, task: str):
        first = TextMessage(content="Draft", source="writer")
        final = TextMessage(content="Revised draft", source="writer")
        yield first
        yield final
        yield TaskResult(messages=[first, final])


def repeated_message_team() -> RepeatedMessageTeam:
    return RepeatedMessageTeam()


def failing_bridged_agent(*, agentflow_tools=None) -> AssistantAgent:
    usage = RequestUsage(prompt_tokens=5, completion_tokens=2)
    call = FunctionCall(id="bridge-call", name="bridge_failure", arguments="{}")
    responses = [
        CreateResult(content=[call], finish_reason="function_calls", usage=usage, cached=False),
        CreateResult(content="failed", finish_reason="stop", usage=usage, cached=False),
    ]
    client = ReplayChatCompletionClient(
        responses,
        model_info=ModelInfo(
            vision=False,
            function_calling=True,
            json_output=False,
            family="unknown",
        ),
    )
    tools = list(agentflow_tools or [])
    return AssistantAgent(
        name="assistant",
        model_client=client,
        tools=tools,
        reflect_on_tool_use=False,
    )


def not_a_runnable() -> TaskResult:
    return TaskResult(messages=[TextMessage(content="nope", source="assistant")])


@pytest.mark.asyncio
async def test_factory_run_streams_messages_and_usage() -> None:
    adapter = create_adapter()
    ctx = RecordingContext({"agent_factory": factory_reference("text_agent")})

    result = await adapter.run(ctx)

    assert isinstance(adapter, AutoGenAdapter)
    assert result.status == RunStatus.SUCCEEDED
    assert result.output == {"reply": "Hello from AutoGen"}
    assert ctx.event("step.started") == [{"index": 0, "node": "autogen"}]
    assert "".join(item["delta"] for item in ctx.event("token.delta")) == "Hello from AutoGen"
    assert [item["role"] for item in ctx.event("message.created")] == ["user", "assistant"]
    assert ctx.event("step.completed")[0]["tokens_in"] > 0
    assert ctx.event("step.completed")[0]["output"] == result.output


@pytest.mark.asyncio
async def test_native_tool_events_use_agentflow_ids() -> None:
    ctx = RecordingContext({"agent_factory": factory_reference("tool_agent")})

    result = await AutoGenAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    started = ctx.event("tool_call.started")[0]
    completed = ctx.event("tool_call.completed")[0]
    assert started["name"] == "echo"
    assert started["arguments"] == {"text": "ping"}
    assert len(started["call_id"]) == 26
    assert started["call_id"] != "provider-call-id"
    assert completed["call_id"] == started["call_id"]
    assert completed["result"] == {"result": "echo:ping"}
    assert completed["error"] is None


@pytest.mark.asyncio
async def test_agentflow_builtin_tool_is_injected_without_duplicate_events() -> None:
    ctx = RecordingContext(
        {
            "agent_factory": factory_reference("bridged_tool_agent"),
            "tools": ["echo"],
        }
    )

    result = await AutoGenAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    started = ctx.event("tool_call.started")
    completed = ctx.event("tool_call.completed")
    assert len(started) == len(completed) == 1
    assert started[0]["name"] == "echo"
    assert completed[0]["result"] == {"text": "ping"}
    assert completed[0]["call_id"] == started[0]["call_id"]


@pytest.mark.asyncio
async def test_team_run_emits_one_step_per_turn() -> None:
    ctx = RecordingContext(
        {
            "team_factory": factory_reference("create_team"),
            "per_turn_steps": True,
        },
        prompt="collab",
    )

    result = await AutoGenAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    assert result.output["reply"] == "Editor approves"
    assert result.output["replies"] == ["Writer says hi", "Editor approves"]
    assert [step["node"] for step in ctx.event("step.started")] == ["writer", "editor"]
    assert len(ctx.event("step.completed")) == 2


@pytest.mark.asyncio
async def test_team_bridged_tools_follow_the_live_turn_step() -> None:
    ctx = RecordingContext(
        {
            "team_factory": factory_reference("create_bridged_team"),
            "per_turn_steps": True,
            "tools": ["echo"],
        },
        prompt="collab with tools",
    )

    result = await AutoGenAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    assert result.output["replies"] == ["Writer used the bridge", "Editor used the bridge"]
    assert ctx.event("step.started") == [
        {"index": 0, "node": "writer"},
        {"index": 1, "node": "editor"},
    ]
    assert [event["step_index"] for event in ctx.event("tool_call.started")] == [0, 1]
    assert [event["step_index"] for event in ctx.event("tool_call.completed")] == [0, 1]
    assert [event["step_index"] for event in ctx.event("message.created") if event["role"] == "assistant"] == [0, 1]

    for step_index in (0, 1):
        step_position = next(
            index
            for index, (event_type, data) in enumerate(ctx.events)
            if event_type == "step.started" and data["index"] == step_index
        )
        tool_position = next(
            index
            for index, (event_type, data) in enumerate(ctx.events)
            if event_type == "tool_call.started" and data["step_index"] == step_index
        )
        assert step_position < tool_position


@pytest.mark.asyncio
async def test_repeated_messages_from_one_agent_stay_in_the_same_turn_step() -> None:
    ctx = RecordingContext(
        {
            "team_factory": factory_reference("repeated_message_team"),
            "per_turn_steps": True,
        }
    )

    result = await AutoGenAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    assert result.output == {"reply": "Revised draft", "replies": ["Draft", "Revised draft"]}
    assert ctx.event("step.started") == [{"index": 0, "node": "writer"}]
    assert len(ctx.event("step.completed")) == 1
    assert [event["step_index"] for event in ctx.event("message.created") if event["role"] == "assistant"] == [0, 0]


@pytest.mark.asyncio
async def test_invalid_factory_becomes_a_failed_step() -> None:
    ctx = RecordingContext({"agent_factory": factory_reference("not_a_runnable")})

    result = await AutoGenAdapter().run(ctx)

    assert result.status == RunStatus.FAILED
    assert "run_stream" in (result.error or "")
    assert ctx.event("step.failed")[0]["error"] == result.error


@pytest.mark.asyncio
async def test_agentflow_tool_failure_is_emitted_once() -> None:
    async def fail(_arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("bridge exploded")

    register_tool("bridge_failure", fail)
    ctx = RecordingContext(
        {
            "agent_factory": factory_reference("failing_bridged_agent"),
            "tools": ["bridge_failure"],
        }
    )

    result = await AutoGenAdapter().run(ctx)

    assert result.status == RunStatus.FAILED
    assert result.error == "bridge exploded"
    assert len(ctx.event("tool_call.started")) == 1
    assert len(ctx.event("tool_call.completed")) == 1
    assert ctx.event("tool_call.completed")[0]["error"] == "bridge exploded"
