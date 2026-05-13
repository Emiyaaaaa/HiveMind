"""Run lifecycle.

`RunService` is the only place that mutates run state. The HTTP API and any
future SDK route writes through this class so adapters, persistence, and
event broadcasts stay consistent.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.adapters import AdapterContext, get_adapter
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.events import EventBus
from app.models import (
    Agent,
    Checkpoint,
    Message,
    Run,
    RunStatus,
    Step,
    ToolCall,
)
from app.schemas.run import EventType, RunCreate, RunEvent

logger = get_logger("run_service")


class RunNotFound(Exception):
    pass


class AgentNotFound(Exception):
    pass


# Tasks survive beyond a single request, so they are tracked at module scope.
_running_tasks: dict[str, asyncio.Task[Any]] = {}


class RunService:
    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session = session
        self.bus = bus
        # Background adapter tasks need their own session, decoupled from the
        # request-scoped one. Tests can inject a different factory.
        self.session_factory = session_factory or SessionLocal

    async def create_run(self, payload: RunCreate) -> Run:
        agent = await self.session.get(Agent, payload.agent_id)
        if agent is None:
            raise AgentNotFound(payload.agent_id)

        run = Run(
            agent_id=agent.id,
            adapter=payload.adapter or agent.adapter,
            status=RunStatus.PENDING,
            input=payload.input,
            metadata_=payload.metadata,
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)

        await self._broadcast("run.created", run.id, {"agent_id": agent.id})
        return run

    async def start_run(self, run_id: str) -> asyncio.Task[Any]:
        """Kick off the orchestrator for `run_id` as a background task.

        The adapter executes against its own session so concurrent reads
        from the API request that created the run are not blocked.
        """
        run = await self._get_run(run_id)
        if run.status not in (RunStatus.PENDING, RunStatus.WAITING_HUMAN):
            existing = _running_tasks.get(run_id)
            if existing is not None:
                return existing
            return asyncio.create_task(asyncio.sleep(0))

        adapter = get_adapter(run.adapter)
        task = asyncio.create_task(
            self._run_adapter_in_background(run_id, adapter.name)
        )
        _running_tasks[run_id] = task
        return task

    async def _run_adapter_in_background(self, run_id: str, adapter_name: str) -> None:
        try:
            async with self.session_factory() as session:
                inner = RunService(
                    session=session,
                    bus=self.bus,
                    session_factory=self.session_factory,
                )
                run = await inner._get_run(run_id)
                agent = await session.get(Agent, run.agent_id)
                if agent is None:
                    await inner._finalize(
                        run_id, RunStatus.FAILED, error="agent missing"
                    )
                    return

                run.status = RunStatus.RUNNING
                await session.commit()
                await inner._broadcast("run.started", run.id, {})

                ctx = AdapterContext(
                    run_id=run.id,
                    agent_id=agent.id,
                    agent_config=agent.config or {},
                    input=run.input,
                    metadata=run.metadata_,
                    emit=lambda event_type, data: inner._handle_event(
                        run.id, event_type, data
                    ),
                )

                adapter = get_adapter(adapter_name)
                try:
                    result = await adapter.run(ctx)
                except asyncio.CancelledError:
                    await inner._finalize(
                        run_id, RunStatus.CANCELLED, error="cancelled"
                    )
                    raise
                except Exception as exc:
                    logger.exception(
                        "adapter_failed", run_id=run_id, adapter=adapter_name
                    )
                    await inner._finalize(run_id, RunStatus.FAILED, error=str(exc))
                    return

                await inner._finalize(
                    run_id,
                    result.status,
                    output=result.output,
                    error=result.error,
                )
        finally:
            _running_tasks.pop(run_id, None)

    async def cancel_run(self, run_id: str) -> None:
        task = _running_tasks.get(run_id)
        if task is not None:
            task.cancel()
            return
        await self._finalize(run_id, RunStatus.CANCELLED, error="cancelled")

    async def get_run(self, run_id: str, *, with_relations: bool = True) -> Run:
        return await self._get_run(run_id, with_relations=with_relations)

    async def list_runs(self, limit: int = 50) -> list[Run]:
        stmt = select(Run).order_by(Run.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    # ------------------------------------------------------------------ helpers

    async def _get_run(self, run_id: str, *, with_relations: bool = False) -> Run:
        stmt = select(Run).where(Run.id == run_id)
        if with_relations:
            stmt = stmt.options(
                selectinload(Run.steps).selectinload(Step.tool_calls),
                selectinload(Run.messages),
                selectinload(Run.checkpoints),
            )
        try:
            result = await self.session.execute(stmt)
            return result.scalar_one()
        except NoResultFound as exc:
            raise RunNotFound(run_id) from exc

    async def _finalize(
        self,
        run_id: str,
        status: RunStatus,
        *,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        run = await self._get_run(run_id)
        run.status = status
        if output is not None:
            run.output = output
        if error is not None:
            run.error = error
        await self.session.commit()

        if status == RunStatus.SUCCEEDED:
            await self._broadcast("run.completed", run_id, {"output": output})
        elif status == RunStatus.FAILED:
            await self._broadcast("run.failed", run_id, {"error": error})
        elif status == RunStatus.CANCELLED:
            await self._broadcast("run.cancelled", run_id, {"error": error})

    async def _broadcast(
        self, event_type: EventType, run_id: str, data: dict[str, Any]
    ) -> None:
        event = RunEvent(
            type=event_type,
            run_id=run_id,
            at=datetime.now(UTC),
            data=data,
        )
        await self.bus.publish(event)

    async def _handle_event(
        self, run_id: str, event_type: EventType, data: dict[str, Any]
    ) -> None:
        """Translate adapter events into DB writes + SSE broadcast."""
        if event_type == "step.started":
            step = Step(
                run_id=run_id,
                index=data["index"],
                node=data["node"],
                input=data.get("input", {}),
                status=RunStatus.RUNNING,
            )
            self.session.add(step)
            await self.session.commit()
        elif event_type == "step.completed":
            step = await self._find_step(run_id, data["index"])
            if step is not None:
                step.status = RunStatus.SUCCEEDED
                step.output = data.get("output")
                step.latency_ms = data.get("latency_ms")
                step.tokens_in = data.get("tokens_in")
                step.tokens_out = data.get("tokens_out")
                await self.session.commit()
        elif event_type == "step.failed":
            step = await self._find_step(run_id, data["index"])
            if step is not None:
                step.status = RunStatus.FAILED
                step.error = data.get("error")
                await self.session.commit()
        elif event_type == "message.created":
            index = await self._next_message_index(run_id)
            message = Message(
                run_id=run_id,
                index=index,
                role=data["role"],
                name=data.get("name"),
                content=data.get("content", ""),
                tool_call_id=data.get("tool_call_id"),
                extra=data.get("extra", {}),
            )
            self.session.add(message)
            await self.session.commit()
        elif event_type == "tool_call.started":
            step = await self._find_step(run_id, data["step_index"])
            if step is not None:
                call = ToolCall(
                    step_id=step.id,
                    name=data["name"],
                    arguments=data.get("arguments", {}),
                )
                self.session.add(call)
                await self.session.commit()
        elif event_type == "tool_call.completed":
            step = await self._find_step(run_id, data["step_index"])
            if step is not None:
                stmt = (
                    select(ToolCall)
                    .where(ToolCall.step_id == step.id, ToolCall.name == data["name"])
                    .order_by(ToolCall.created_at.desc())
                    .limit(1)
                )
                result = await self.session.execute(stmt)
                call = result.scalar_one_or_none()
                if call is not None:
                    call.result = data.get("result")
                    call.error = data.get("error")
                    call.latency_ms = data.get("latency_ms")
                    await self.session.commit()
        elif event_type == "checkpoint.created":
            cp_index = await self._next_checkpoint_index(run_id)
            cp = Checkpoint(
                run_id=run_id,
                index=cp_index,
                label=data.get("label"),
                state=data.get("state", {}),
            )
            self.session.add(cp)
            await self.session.commit()

        await self._broadcast(event_type, run_id, data)

    async def _find_step(self, run_id: str, index: int) -> Step | None:
        stmt = select(Step).where(Step.run_id == run_id, Step.index == index)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _next_message_index(self, run_id: str) -> int:
        stmt = (
            select(Message.index)
            .where(Message.run_id == run_id)
            .order_by(Message.index.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        last = result.scalar_one_or_none()
        return 0 if last is None else last + 1

    async def _next_checkpoint_index(self, run_id: str) -> int:
        stmt = (
            select(Checkpoint.index)
            .where(Checkpoint.run_id == run_id)
            .order_by(Checkpoint.index.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        last = result.scalar_one_or_none()
        return 0 if last is None else last + 1
