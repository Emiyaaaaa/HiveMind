"""ReAct tool failure recovery — policy, observations, parallel, and exhaustion."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from sqlalchemy import select

from app.adapters.base import AdapterContext
from app.adapters.langgraph_adapter import (
    LangGraphAdapter,
    ModelResponse,
    ToolRecoveryExhaustedError,
    parse_tool_error_policy,
)
from app.adapters.tool_errors import RecoverableToolError, build_safe_tool_error_observation
from app.adapters.tool_registry import register_tool
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.events import get_event_bus
from app.models import Agent, Step, ToolCall
from app.models.run import RunStatus as RunStatusEnum
from app.schemas.run import RunCreate
from app.services.run_service import RunService
from app.worker.cancel import InMemoryCancelRegistry
from app.worker.executor import RunExecutor


class _RecordingContext(AdapterContext):
    def __init__(self, **kwargs: Any) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        super().__init__(
            run_id="01TEST",
            agent_id="01AGENT",
            agent_config={},
            input={"prompt": "hello"},
            emit=self._emit,
            **kwargs,
        )

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def _run_messages_from_events(
    events: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event, data in events:
        if event != "message.created":
            continue
        msg: dict[str, Any] = {"role": data["role"], "content": data.get("content", "")}
        if data.get("tool_call_id"):
            msg["tool_call_id"] = data["tool_call_id"]
        extra = data.get("extra") or {}
        if extra.get("tool_calls"):
            msg["tool_calls"] = extra["tool_calls"]
        rows.append(msg)
    return rows


def _agent_graph_config(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "model": "openai/gpt-4o-mini",
        "graph": {
            "nodes": [{"id": "worker", "type": "agent"}],
            "edges": [
                ["__start__", "worker"],
                ["worker", "__end__"],
            ],
        },
    }
    base.update(overrides)
    return base


async def _recoverable_fail(_args: dict[str, Any]) -> dict[str, Any]:
    raise RecoverableToolError(
        code="bad_args",
        public_message="Fix your parameters and try again.",
        internal_message="secret raw validation error",
    )


async def _fatal_fail(_args: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("programming bug")


async def _slow_success(args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.05)
    return {"text": str(args.get("text", "ok"))}


@pytest.fixture(autouse=True)
def _register_recovery_tools():
    register_tool("recovery_fail", _recoverable_fail, overwrite=True)
    register_tool("recovery_fatal", _fatal_fail, overwrite=True)
    register_tool("recovery_slow", _slow_success, overwrite=True)
    yield


def test_parse_tool_error_policy_defaults_to_fail_fast():
    assert parse_tool_error_policy({}) == "fail_fast"


def test_parse_tool_error_policy_rejects_invalid():
    with pytest.raises(ValueError, match="invalid tool_error_policy"):
        parse_tool_error_policy({"tool_error_policy": "retry"})


def test_build_safe_observation_excludes_internal_message():
    exc = RecoverableToolError(
        code="bad_args",
        public_message="safe text",
        internal_message="secret raw error",
    )
    obs = build_safe_tool_error_observation(tool_name="recovery_fail", exc=exc)
    serialized = json.dumps(obs)
    assert obs["ok"] is False
    assert obs["error"]["type"] == "recoverable_tool_error"
    assert obs["error"]["code"] == "bad_args"
    assert obs["error"]["message"] == "safe text"
    assert "secret" not in serialized
    assert "traceback" not in serialized


@pytest.mark.asyncio
async def test_fail_fast_on_recoverable_error():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(tools=["recovery_fail"])
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.FAILED
    assert "secret raw validation error" in (result.error or "")


@pytest.mark.asyncio
async def test_explicit_fail_fast_on_recoverable_error():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["recovery_fail"],
        tool_error_policy="fail_fast",
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.FAILED


@pytest.mark.asyncio
async def test_feedback_converts_recoverable_to_observation_and_recovers():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["recovery_fail"],
        tool_error_policy="feedback",
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.SUCCEEDED
    reply = (result.output or {}).get("reply", "")
    assert "recoverable_tool_error" in reply or "Fix your parameters" in reply

    completed = [
        data for event, data in ctx.events if event == "tool_call.completed"
    ]
    assert completed[0]["error"] == "secret raw validation error"
    assert "secret" not in reply


@pytest.mark.asyncio
async def test_feedback_fatal_runtime_error_still_fails():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["recovery_fatal"],
        tool_error_policy="feedback",
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.FAILED
    assert "programming bug" in (result.error or "")


@pytest.mark.asyncio
async def test_invalid_policy_fails_before_tool_execution():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["echo"],
        tool_error_policy="retry",
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.FAILED
    assert "invalid tool_error_policy" in (result.error or "")
    assert not any(e.startswith("tool_call.") for e, _ in ctx.events)


@pytest.mark.asyncio
async def test_feedback_fallback_tool_success(monkeypatch: pytest.MonkeyPatch):
    scripted: list[ModelResponse] = [
        ModelResponse(
            content="",
            tool_calls=[
                {
                    "id": "call_fail",
                    "name": "recovery_fail",
                    "arguments": {},
                }
            ],
            tokens_in=1,
            tokens_out=1,
        ),
        ModelResponse(
            content="",
            tool_calls=[
                {
                    "id": "call_echo",
                    "name": "echo",
                    "arguments": {"text": "hi"},
                }
            ],
            tokens_in=1,
            tokens_out=1,
        ),
        ModelResponse(content="fallback succeeded", tokens_in=1, tokens_out=1),
    ]
    call_idx = {"n": 0}

    async def _scripted_invoke(
        self: LangGraphAdapter,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResponse:
        idx = min(call_idx["n"], len(scripted) - 1)
        call_idx["n"] += 1
        return scripted[idx]

    monkeypatch.setattr(LangGraphAdapter, "_invoke_model", _scripted_invoke)

    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["recovery_fail", "echo"],
        tool_error_policy="feedback",
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.SUCCEEDED
    assert result.output == {"reply": "fallback succeeded"}
    assert call_idx["n"] == 3


@pytest.mark.asyncio
async def test_feedback_parallel_success_and_recoverable(monkeypatch: pytest.MonkeyPatch):
    async def _scripted_invoke(
        self: LangGraphAdapter,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResponse:
        if not any(m.get("role") == "tool" for m in messages):
            return ModelResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call_ok",
                        "name": "echo",
                        "arguments": {"text": "a"},
                    },
                    {
                        "id": "call_bad",
                        "name": "recovery_fail",
                        "arguments": {},
                    },
                ],
                tokens_in=1,
                tokens_out=1,
            )
        return ModelResponse(content="used partial results", tokens_in=1, tokens_out=1)

    monkeypatch.setattr(LangGraphAdapter, "_invoke_model", _scripted_invoke)

    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["echo", "recovery_fail"],
        tool_error_policy="feedback",
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.SUCCEEDED

    checkpoints = [
        data for event, data in ctx.events if event == "checkpoint.created"
    ]
    graph_state = checkpoints[-1]["state"]["graph_state"]
    assert "messages" not in graph_state
    messages = _run_messages_from_events(ctx.events)
    tool_msgs = [
        (m["tool_call_id"], json.loads(m["content"]))
        for m in messages
        if m.get("role") == "tool"
    ]
    assert len(tool_msgs) == 2
    assert tool_msgs[0][0] == "call_ok"
    assert tool_msgs[1][0] == "call_bad"
    assert tool_msgs[0][1] == {"text": "a"}
    assert tool_msgs[1][1]["ok"] is False


@pytest.mark.asyncio
async def test_feedback_parallel_fatal_fails_step(monkeypatch: pytest.MonkeyPatch):
    async def _scripted_invoke(
        self: LangGraphAdapter,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResponse:
        return ModelResponse(
            content="",
            tool_calls=[
                {
                    "id": "call_ok",
                    "name": "echo",
                    "arguments": {"text": "a"},
                },
                {
                    "id": "call_fatal",
                    "name": "recovery_fatal",
                    "arguments": {},
                },
            ],
            tokens_in=1,
            tokens_out=1,
        )

    monkeypatch.setattr(LangGraphAdapter, "_invoke_model", _scripted_invoke)

    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["echo", "recovery_fatal"],
        tool_error_policy="feedback",
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.FAILED
    assert "programming bug" in (result.error or "")


@pytest.mark.asyncio
async def test_feedback_recovery_exhausted(monkeypatch: pytest.MonkeyPatch):
    async def _always_tool_call(
        self: LangGraphAdapter,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResponse:
        return ModelResponse(
            content="",
            tool_calls=[
                {
                    "id": "call_fail",
                    "name": "recovery_fail",
                    "arguments": {},
                }
            ],
            tokens_in=1,
            tokens_out=1,
        )

    monkeypatch.setattr(LangGraphAdapter, "_invoke_model", _always_tool_call)

    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["recovery_fail"],
        tool_error_policy="feedback",
        max_tool_rounds=2,
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.FAILED
    assert "tool_recovery_exhausted" in (result.error or "")
    assert "max_tool_rounds=2" in (result.error or "")


@pytest.mark.asyncio
async def test_max_rounds_without_recoverable_feedback_keeps_legacy_success(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _always_tool_call(
        self: LangGraphAdapter,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResponse:
        return ModelResponse(
            content="",
            tool_calls=[
                {"id": "call_echo", "name": "echo", "arguments": {"text": "x"}}
            ],
            tokens_in=1,
            tokens_out=1,
        )

    monkeypatch.setattr(LangGraphAdapter, "_invoke_model", _always_tool_call)

    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["echo"],
        tool_error_policy="feedback",
        max_tool_rounds=1,
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatusEnum.SUCCEEDED
    assert "reached max_tool_rounds=1" in (result.output or {}).get("reply", "")


@pytest.mark.asyncio
async def test_provider_tool_call_id_paired_with_lifecycle_call_id():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = _agent_graph_config(
        tools=["recovery_fail"],
        tool_error_policy="feedback",
    )
    await adapter.run(ctx)

    started = [d for e, d in ctx.events if e == "tool_call.started"]
    completed = [d for e, d in ctx.events if e == "tool_call.completed"]
    checkpoints = [
        data for event, data in ctx.events if event == "checkpoint.created"
    ]
    tool_msgs = [
        m for m in _run_messages_from_events(ctx.events) if m.get("role") == "tool"
    ]
    assert started[0]["call_id"] == completed[0]["call_id"]
    assert len(started[0]["call_id"]) == 26
    assert tool_msgs[0]["tool_call_id"] == "call_recovery_fail"
    assert tool_msgs[0]["tool_call_id"] != started[0]["call_id"]


def test_tool_recovery_exhausted_error_message():
    err = ToolRecoveryExhaustedError(4)
    assert "tool_recovery_exhausted" in str(err)
    assert "max_tool_rounds=4" in str(err)


@pytest.mark.asyncio
async def test_executor_persists_raw_error_but_not_in_model_observation(
    monkeypatch: pytest.MonkeyPatch,
):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async def _scripted_invoke(
        self: LangGraphAdapter,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelResponse:
        if not any(m.get("role") == "tool" for m in messages):
            return ModelResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call_fail",
                        "name": "recovery_fail",
                        "arguments": {},
                    }
                ],
                tokens_in=1,
                tokens_out=1,
            )
        return ModelResponse(content="recovered", tokens_in=1, tokens_out=1)

    monkeypatch.setattr(LangGraphAdapter, "_invoke_model", _scripted_invoke)

    bus = get_event_bus()
    async with SessionLocal() as session:
        agent = Agent(
            name="recovery-agent",
            adapter="langgraph",
            config=_agent_graph_config(
                tools=["recovery_fail"],
                tool_error_policy="feedback",
            ),
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        service = RunService(session=session, bus=bus)
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={"prompt": "hello"})
        )
        run_id = run.id

    executor = RunExecutor(bus=bus, cancel_registry=InMemoryCancelRegistry())
    await executor.execute(run_id, "langgraph")

    async with SessionLocal() as session:
        from app.models.run import Run

        finished = (
            await session.execute(select(Run).where(Run.id == run_id))
        ).scalar_one()
        assert finished.status == RunStatusEnum.SUCCEEDED

        step = (
            await session.execute(
                select(Step).where(Step.run_id == run_id, Step.index == 0)
            )
        ).scalar_one()
        calls = (
            await session.execute(
                select(ToolCall).where(ToolCall.step_id == step.id)
            )
        ).scalars().all()
        assert len(calls) == 1
        assert calls[0].error == "secret raw validation error"
        assert calls[0].result is None
