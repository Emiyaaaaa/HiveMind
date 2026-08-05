"""ToolCall started/completed association — including parallel same-name calls."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter, new_tool_call_id
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.events import get_event_bus
from app.models import Agent, RunStatus, Step, ToolCall
from app.schemas.run import RunCreate
from app.services.run_service import RunService
from app.worker.cancel import InMemoryCancelRegistry
from app.worker.executor import RunExecutor


@pytest.fixture(autouse=True)
async def schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_agent(session, adapter: str = "echo") -> Agent:
    agent = Agent(name=f"agent-{id(session)}", adapter=adapter, config={})
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@pytest.mark.asyncio
async def test_tool_call_completed_matches_by_call_id_not_latest_name():
    """Out-of-order same-name completions must not clobber the wrong row."""
    bus = get_event_bus()

    async with SessionLocal() as session:
        agent = await _make_agent(session)
        service = RunService(session=session, bus=bus)
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={"prompt": "x"})
        )

        await service._handle_event(
            run.id, "step.started", {"index": 0, "node": "tools"}
        )

        first_id = new_tool_call_id()
        second_id = new_tool_call_id()

        await service._handle_event(
            run.id,
            "tool_call.started",
            {
                "step_index": 0,
                "name": "echo",
                "arguments": {"text": "a"},
                "call_id": first_id,
            },
        )
        await service._handle_event(
            run.id,
            "tool_call.started",
            {
                "step_index": 0,
                "name": "echo",
                "arguments": {"text": "b"},
                "call_id": second_id,
            },
        )

        # Complete the *second* call first (parallel out-of-order).
        await service._handle_event(
            run.id,
            "tool_call.completed",
            {
                "step_index": 0,
                "name": "echo",
                "call_id": second_id,
                "result": {"text": "b"},
                "latency_ms": 5,
            },
        )
        await service._handle_event(
            run.id,
            "tool_call.completed",
            {
                "step_index": 0,
                "name": "echo",
                "call_id": first_id,
                "result": {"text": "a"},
                "latency_ms": 9,
            },
        )

    async with SessionLocal() as session:
        step = (
            await session.execute(
                select(Step).where(Step.run_id == run.id, Step.index == 0)
            )
        ).scalar_one()
        calls = (
            await session.execute(
                select(ToolCall)
                .where(ToolCall.step_id == step.id)
                .order_by(ToolCall.created_at.asc())
            )
        ).scalars().all()

        assert len(calls) == 2
        by_id = {c.id: c for c in calls}
        assert by_id[first_id].arguments == {"text": "a"}
        assert by_id[first_id].result == {"text": "a"}
        assert by_id[first_id].latency_ms == 9
        assert by_id[second_id].arguments == {"text": "b"}
        assert by_id[second_id].result == {"text": "b"}
        assert by_id[second_id].latency_ms == 5


@pytest.mark.asyncio
async def test_tool_call_completed_fallback_uses_oldest_incomplete():
    bus = get_event_bus()

    async with SessionLocal() as session:
        agent = await _make_agent(session)
        service = RunService(session=session, bus=bus)
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={"prompt": "x"})
        )
        await service._handle_event(
            run.id, "step.started", {"index": 0, "node": "tools"}
        )
        await service._handle_event(
            run.id,
            "tool_call.started",
            {"step_index": 0, "name": "echo", "arguments": {"n": 1}},
        )
        await service._handle_event(
            run.id,
            "tool_call.started",
            {"step_index": 0, "name": "echo", "arguments": {"n": 2}},
        )
        # Legacy completed event without call_id → oldest pending.
        await service._handle_event(
            run.id,
            "tool_call.completed",
            {"step_index": 0, "name": "echo", "result": {"n": 1}},
        )

    async with SessionLocal() as session:
        step = (
            await session.execute(
                select(Step).where(Step.run_id == run.id, Step.index == 0)
            )
        ).scalar_one()
        calls = (
            await session.execute(
                select(ToolCall)
                .where(ToolCall.step_id == step.id)
                .order_by(ToolCall.created_at.asc())
            )
        ).scalars().all()
        assert calls[0].result == {"n": 1}
        assert calls[1].result is None


class _ParallelSameNameAdapter(OrchestratorAdapter):
    name = "parallel_tools"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        await ctx.emit_step_started(index=0, node="parallel")

        async def _one(label: str, delay: float) -> None:
            call_id = await ctx.emit_tool_call_started(
                step_index=0,
                name="echo",
                arguments={"text": label},
            )
            await asyncio.sleep(delay)
            await ctx.emit_tool_call_completed(
                step_index=0,
                name="echo",
                call_id=call_id,
                result={"text": label},
            )

        # Faster "b" finishes first; call_id must keep results on the right rows.
        await asyncio.gather(_one("a", 0.05), _one("b", 0.01))
        await ctx.emit_step_completed(index=0, node="parallel", output={"ok": True})
        return AdapterResult(status=RunStatus.SUCCEEDED, output={"ok": True})


@pytest.mark.asyncio
async def test_parallel_tool_emits_associate_via_executor_lock():
    from app.adapters import register_adapter

    adapter = _ParallelSameNameAdapter()
    try:
        register_adapter("parallel_tools", adapter)
    except ValueError:
        pass

    bus = get_event_bus()
    async with SessionLocal() as session:
        agent = await _make_agent(session, adapter="parallel_tools")
        service = RunService(session=session, bus=bus)
        run = await service.create_run(
            RunCreate(agent_id=agent.id, input={"prompt": "x"})
        )
        run_id = run.id

    executor = RunExecutor(bus=bus, cancel_registry=InMemoryCancelRegistry())
    await executor.execute(run_id, "parallel_tools")

    async with SessionLocal() as session:
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
        assert len(calls) == 2
        results = {c.arguments["text"]: c.result for c in calls}
        assert results == {"a": {"text": "a"}, "b": {"text": "b"}}
        assert all(c.error is None for c in calls)
