"""Fan-out batch Runs for one Agent."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import EventBus
from app.models import Agent, Run, RunBatch, RunStatus
from app.schemas.batch import BatchCreate, BatchRead
from app.schemas.run import RunCreate
from app.services.agent_versions import (
    AGENT_VERSION_METADATA_KEY,
    INTERNAL_METADATA_KEY,
)
from app.services.run_service import AgentNotFound, RunService

MAX_BATCH_ITEMS = 100
TERMINAL = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}


class BatchNotFound(Exception):
    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        super().__init__(batch_id)


class BatchValidationError(Exception):
    pass


def _pin_metadata(
    base: dict[str, Any],
    *,
    agent_version: int,
    batch_id: str,
) -> dict[str, Any]:
    meta = dict(base or {})
    meta[INTERNAL_METADATA_KEY] = {
        AGENT_VERSION_METADATA_KEY: agent_version,
        "batch_id": batch_id,
    }
    return meta


def batch_progress(runs: list[Run]) -> tuple[str, int, int]:
    total = len(runs)
    completed = sum(1 for run in runs if run.status in TERMINAL)
    if completed == total and total > 0:
        status = "completed"
    elif all(run.status == RunStatus.PENDING for run in runs):
        status = "pending"
    else:
        status = "running"
    return status, total, completed


class BatchService:
    def __init__(self, session: AsyncSession, bus: EventBus) -> None:
        self.session = session
        self.bus = bus
        self.runs = RunService(session=session, bus=bus)

    async def create_batch(
        self,
        payload: BatchCreate,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> BatchRead:
        if not payload.items or len(payload.items) > MAX_BATCH_ITEMS:
            raise BatchValidationError(
                f"items must contain 1–{MAX_BATCH_ITEMS} entries"
            )

        agent = await self.session.get(Agent, payload.agent_id)
        if (
            agent is None
            or (tenant_id is not None and agent.tenant_id != tenant_id)
            or (project_id is not None and agent.project_id != project_id)
            or (agent_id is not None and agent.id != agent_id)
        ):
            raise AgentNotFound(payload.agent_id)

        batch = RunBatch(
            tenant_id=agent.tenant_id,
            project_id=agent.project_id,
            agent_id=agent.id,
            run_ids=[],
        )
        self.session.add(batch)
        await self.session.flush()

        created: list[Run] = []
        for item in payload.items:
            merged_meta = {**(payload.metadata or {}), **(item.metadata or {})}
            run = await self.runs.create_run(
                RunCreate(
                    agent_id=agent.id,
                    input=item.input,
                    metadata=_pin_metadata(
                        merged_meta,
                        agent_version=agent.version,
                        batch_id=batch.id,
                    ),
                    adapter=payload.adapter,
                ),
                tenant_id=tenant_id,
                project_id=project_id,
                agent_id=agent_id,
            )
            created.append(run)

        batch.run_ids = [run.id for run in created]
        await self.session.commit()
        await self.session.refresh(batch)

        for run in created:
            await self.runs.start_run(run.id)

        return await self._to_read(batch)

    async def list_batches(
        self,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[BatchRead]:
        capped = max(1, min(limit, 200))
        stmt = select(RunBatch).order_by(RunBatch.created_at.desc()).limit(capped)
        if tenant_id is not None:
            stmt = stmt.where(RunBatch.tenant_id == tenant_id)
        if project_id is not None:
            stmt = stmt.where(RunBatch.project_id == project_id)
        if agent_id is not None:
            stmt = stmt.where(RunBatch.agent_id == agent_id)
        rows = (await self.session.scalars(stmt)).all()
        return [await self._to_read(row) for row in rows]

    async def get_batch(
        self,
        batch_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> BatchRead:
        batch = await self._require(
            batch_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        return await self._to_read(batch)

    async def list_batch_runs(
        self,
        batch_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[Run]:
        batch = await self._require(
            batch_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        runs_by_id = {
            run.id: run
            for run in await self._load_runs(list(batch.run_ids or []))
        }
        return [runs_by_id[rid] for rid in batch.run_ids if rid in runs_by_id]

    async def _require(
        self,
        batch_id: str,
        *,
        tenant_id: str | None,
        project_id: str | None,
        agent_id: str | None,
    ) -> RunBatch:
        batch = await self.session.get(RunBatch, batch_id)
        if (
            batch is None
            or (tenant_id is not None and batch.tenant_id != tenant_id)
            or (project_id is not None and batch.project_id != project_id)
            or (agent_id is not None and batch.agent_id != agent_id)
        ):
            raise BatchNotFound(batch_id)
        return batch

    async def _load_runs(self, run_ids: list[str]) -> list[Run]:
        if not run_ids:
            return []
        stmt = select(Run).where(Run.id.in_(run_ids))
        return list((await self.session.scalars(stmt)).all())

    async def _to_read(self, batch: RunBatch) -> BatchRead:
        runs = await self._load_runs(list(batch.run_ids or []))
        by_id = {run.id: run for run in runs}
        ordered = [by_id[rid] for rid in batch.run_ids if rid in by_id]
        status, total, completed = batch_progress(ordered)
        return BatchRead(
            id=batch.id,
            agent_id=batch.agent_id,
            status=status,
            total=total,
            completed=completed,
            run_ids=list(batch.run_ids or []),
            created_at=batch.created_at,
        )
