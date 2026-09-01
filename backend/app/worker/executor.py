"""Reusable adapter execution for both inline (FastAPI) and queue (worker) modes.

``RunExecutor.execute`` performs the exact same sequence ``RunService`` used
to perform inline:

1. mark the run RUNNING and broadcast ``run.started``,
2. construct an ``AdapterContext`` whose ``emit`` callback persists rows
   (via ``RunService._handle_event``) and re-publishes the event,
3. await ``adapter.run(ctx)``,
4. write the terminal state (succeeded/failed/cancelled).

In queue mode a background watcher polls the cancellation registry that the
Java API populates. On a cancel request the executor task is cancelled and
the run finalises as ``RunStatus.CANCELLED``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.adapters.base import (
    AdapterContext,
    AdapterResult,
    OrchestratorAdapter,
    get_adapter,
)
from app.core.logging import get_logger
from app.core.telemetry import trace_adapter_run
from app.db.session import SessionLocal
from app.events import EventBus
from app.models import Agent, RunStatus
from app.runtime.resume_context import (
    RunResumeContext,
    parse_resume_context,
    without_resume_metadata,
)
from app.schemas.run import EventType
from app.services.agent_versions import (
    InvalidAgentVersionMetadata,
    agent_version_from_metadata,
    get_agent_version,
)
from app.worker.cancel import CancelRegistry, InMemoryCancelRegistry

logger = get_logger("worker.executor")


class RunExecutor:
    def __init__(
        self,
        *,
        bus: EventBus,
        session_factory: async_sessionmaker | None = None,
        cancel_registry: CancelRegistry | None = None,
    ) -> None:
        self.bus = bus
        self.session_factory = session_factory or SessionLocal
        self.cancel_registry = cancel_registry or InMemoryCancelRegistry()

    async def execute(self, run_id: str, adapter_name: str) -> None:
        """Drive a single run from PENDING/WAITING_HUMAN to a terminal state."""

        # Import lazily so RunService can import RunExecutor without circularity.
        from app.services.run_service import RunService

        async with self.session_factory() as session:
            service = RunService(
                session=session,
                bus=self.bus,
                session_factory=self.session_factory,
            )

            run = await service._get_run(run_id)
            agent = await session.get(Agent, run.agent_id)
            if agent is None:
                await service._finalize(run_id, RunStatus.FAILED, error="agent missing")
                return

            # Honour a cancel that arrived before the worker picked up the job.
            if await self.cancel_registry.is_cancelled(run_id):
                await service._finalize(run_id, RunStatus.CANCELLED, error="cancelled")
                await self._safe_clear_cancel(run_id)
                return

            try:
                agent_version = agent_version_from_metadata(run.metadata_)
            except InvalidAgentVersionMetadata as exc:
                await service._finalize(
                    run_id,
                    RunStatus.FAILED,
                    error=f"invalid agent version metadata: {exc}",
                )
                return

            if agent_version is None:
                agent_config = dict(agent.config or {})
            else:
                snapshot = await get_agent_version(session, run.agent_id, agent_version)
                if snapshot is None:
                    await service._finalize(
                        run_id,
                        RunStatus.FAILED,
                        error=(
                            "agent version snapshot missing: "
                            f"agent_id={run.agent_id}, version={agent_version}"
                        ),
                    )
                    return
                agent_config = dict(snapshot.config or {})

            resume_ctx = parse_resume_context(run.metadata_)
            if resume_ctx is not None:
                run.metadata_ = without_resume_metadata(dict(run.metadata_ or {}))

            # Worker crash / Temporal activity retry: the row is still RUNNING
            # (or WAITING_HUMAN if a resume signal raced). Resume from the
            # latest checkpoint so a 24h+ run does not start from scratch.
            if resume_ctx is None and run.status in (
                RunStatus.RUNNING,
                RunStatus.WAITING_HUMAN,
            ):
                resume_ctx = await self._recover_resume(service, run.id, run.status)

            step_index_base = 0
            if resume_ctx is not None and resume_ctx.mode in ("retry", "resume"):
                step_index_base = (await service._max_step_index(run.id)) + 1

            run_messages = None
            if resume_ctx is not None:
                run_messages = await service.load_run_messages(run.id)

            run.status = RunStatus.RUNNING
            await session.commit()
            await service._broadcast("run.started", run.id, {})

            # Serialize DB writes: adapters may emit from concurrent tasks
            # (e.g. parallel tool calls) while sharing one AsyncSession.
            emit_lock = asyncio.Lock()

            async def _emit(event_type: EventType, data: dict[str, Any]) -> None:
                async with emit_lock:
                    await service._handle_event(run.id, event_type, data)

            ctx = AdapterContext(
                run_id=run.id,
                agent_id=agent.id,
                agent_config=agent_config,
                input=run.input,
                metadata=run.metadata_,
                resume=resume_ctx,
                run_messages=run_messages,
                step_index_base=step_index_base,
                emit=_emit,
            )

            adapter = get_adapter(adapter_name)
            task = asyncio.current_task()
            watcher = asyncio.create_task(self._cancel_watcher(run.id, task))
            try:
                try:
                    result = await trace_adapter_run(
                        adapter_name,
                        run_id,
                        self._invoke_adapter(adapter, ctx, resume_ctx),
                    )
                except asyncio.CancelledError:
                    # Cancellation may interrupt a flush; clear the session
                    # so the finalising write can proceed.
                    await session.rollback()
                    await service._finalize(
                        run_id, RunStatus.CANCELLED, error="cancelled"
                    )
                    raise
                except Exception as exc:
                    logger.exception("adapter_failed", run_id=run_id, adapter=adapter_name)
                    await session.rollback()
                    await service._finalize(run_id, RunStatus.FAILED, error=str(exc))
                    return

                await service._finalize(
                    run_id,
                    result.status,
                    output=result.output,
                    error=result.error,
                )
            finally:
                watcher.cancel()
                try:
                    await watcher
                except (asyncio.CancelledError, Exception):
                    pass
                await self._safe_clear_cancel(run_id)

    async def _cancel_watcher(
        self, run_id: str, target: asyncio.Task[Any] | None
    ) -> None:
        if target is None:
            return
        try:
            while not target.done():
                if await self.cancel_registry.is_cancelled(run_id):
                    logger.info("cancel_signal.received", run_id=run_id)
                    target.cancel()
                    return
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            pass

    async def _recover_resume(
        self, service: Any, run_id: str, status: RunStatus
    ) -> RunResumeContext:
        latest = await service._latest_checkpoint(run_id)
        mode = "resume" if status == RunStatus.WAITING_HUMAN else "retry"
        if latest is None:
            return RunResumeContext(mode=mode)
        return RunResumeContext(
            mode=mode,
            checkpoint_state=latest.state,
            checkpoint_index=latest.index,
        )

    async def _invoke_adapter(
        self,
        adapter: OrchestratorAdapter,
        ctx: AdapterContext,
        resume_ctx: object,
    ) -> AdapterResult:
        if isinstance(resume_ctx, RunResumeContext):
            if resume_ctx.mode == "retry":
                return await adapter.retry(ctx)
            if resume_ctx.mode == "resume":
                return await adapter.resume(ctx)
        return await adapter.run(ctx)

    async def _safe_clear_cancel(self, run_id: str) -> None:
        try:
            await self.cancel_registry.clear(run_id)
        except Exception:  # pragma: no cover - best effort
            logger.exception("cancel_clear_failed", run_id=run_id)
