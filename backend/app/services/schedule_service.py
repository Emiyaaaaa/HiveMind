"""Recurring Run schedules and worker sweeper claims."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.events import EventBus
from app.models import Agent, Run, RunSchedule
from app.runtime.schedule_time import (
    ScheduleTimingError,
    next_fire_at,
    validate_cron,
    validate_interval,
)
from app.schemas.schedule import (
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
)
from app.schemas.run import RunCreate
from app.services.agent_versions import (
    AGENT_VERSION_METADATA_KEY,
    INTERNAL_METADATA_KEY,
)
from app.services.run_service import AgentNotFound, RunService


class ScheduleNotFound(Exception):
    def __init__(self, schedule_id: str) -> None:
        self.schedule_id = schedule_id
        super().__init__(schedule_id)


class ScheduleValidationError(Exception):
    pass


def _pin_metadata(
    base: dict[str, Any],
    *,
    agent_version: int,
    schedule_id: str,
) -> dict[str, Any]:
    meta = dict(base or {})
    meta[INTERNAL_METADATA_KEY] = {
        AGENT_VERSION_METADATA_KEY: agent_version,
        "schedule_id": schedule_id,
    }
    return meta


def schedule_to_read(row: RunSchedule) -> ScheduleRead:
    return ScheduleRead.model_validate(
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "name": row.name,
            "cron": row.cron,
            "interval_seconds": row.interval_seconds,
            "timezone": row.timezone,
            "input": dict(row.input or {}),
            "metadata": dict(row.metadata_ or {}),
            "adapter": row.adapter,
            "enabled": row.enabled,
            "next_run_at": row.next_run_at,
            "last_run_at": row.last_run_at,
            "last_run_id": row.last_run_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ScheduleService:
    def __init__(self, session: AsyncSession, bus: EventBus) -> None:
        self.session = session
        self.bus = bus
        self.runs = RunService(session=session, bus=bus)

    async def create_schedule(
        self,
        payload: ScheduleCreate,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> RunSchedule:
        agent = await self._require_agent(
            payload.agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        cron, interval = self._normalize_timing(
            cron=payload.cron,
            interval_seconds=payload.interval_seconds,
            timezone=payload.timezone,
        )
        try:
            nxt = next_fire_at(
                cron=cron,
                interval_seconds=interval,
                timezone=payload.timezone,
            )
        except ScheduleTimingError as exc:
            raise ScheduleValidationError(str(exc)) from exc

        row = RunSchedule(
            tenant_id=agent.tenant_id,
            project_id=agent.project_id,
            agent_id=agent.id,
            name=payload.name,
            cron=cron,
            interval_seconds=interval,
            timezone=payload.timezone or "UTC",
            input=payload.input,
            metadata_=payload.metadata,
            adapter=payload.adapter,
            enabled=payload.enabled,
            next_run_at=nxt,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_schedules(
        self,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[RunSchedule]:
        capped = max(1, min(limit, 200))
        stmt = (
            select(RunSchedule)
            .order_by(RunSchedule.created_at.desc())
            .limit(capped)
        )
        if tenant_id is not None:
            stmt = stmt.where(RunSchedule.tenant_id == tenant_id)
        if project_id is not None:
            stmt = stmt.where(RunSchedule.project_id == project_id)
        if agent_id is not None:
            stmt = stmt.where(RunSchedule.agent_id == agent_id)
        return list((await self.session.scalars(stmt)).all())

    async def get_schedule(
        self,
        schedule_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> RunSchedule:
        return await self._require(
            schedule_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )

    async def update_schedule(
        self,
        schedule_id: str,
        payload: ScheduleUpdate,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> RunSchedule:
        row = await self._require(
            schedule_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        data = payload.model_dump(exclude_unset=True)
        if "name" in data:
            row.name = data["name"]
        if "input" in data and data["input"] is not None:
            row.input = data["input"]
        if "metadata" in data and data["metadata"] is not None:
            row.metadata_ = data["metadata"]
        if "adapter" in data:
            row.adapter = data["adapter"]
        if "enabled" in data and data["enabled"] is not None:
            row.enabled = data["enabled"]
        if "timezone" in data and data["timezone"] is not None:
            row.timezone = data["timezone"]

        timing_touched = (
            "cron" in data or "interval_seconds" in data or "timezone" in data
        )
        cron = data["cron"] if "cron" in data else row.cron
        interval = (
            data["interval_seconds"]
            if "interval_seconds" in data
            else row.interval_seconds
        )
        # Allow PATCH to switch timing mode by setting one and clearing the other.
        if "cron" in data and data["cron"] is not None:
            interval = None
        if "interval_seconds" in data and data["interval_seconds"] is not None:
            cron = None

        if timing_touched:
            try:
                cron, interval = self._normalize_timing(
                    cron=cron,
                    interval_seconds=interval,
                    timezone=row.timezone,
                )
                row.cron = cron
                row.interval_seconds = interval
                row.next_run_at = next_fire_at(
                    cron=cron,
                    interval_seconds=interval,
                    timezone=row.timezone,
                )
            except ScheduleTimingError as exc:
                raise ScheduleValidationError(str(exc)) from exc

        row.updated_at = utcnow()
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def delete_schedule(
        self,
        schedule_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        row = await self._require(
            schedule_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        await self.session.delete(row)
        await self.session.commit()

    async def trigger_schedule(
        self,
        schedule_id: str,
        *,
        advance: bool = False,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> Run:
        row = await self._require(
            schedule_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        run = await self._fire(row, advance=advance)
        await self.session.commit()
        await self.runs.start_run(run.id)
        return run

    async def list_schedule_runs(
        self,
        schedule_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[Run]:
        await self._require(
            schedule_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        capped = max(1, min(limit, 200))
        # Metadata JSON contains schedule_id; filter in Python for SQLite parity.
        stmt = select(Run).order_by(Run.created_at.desc()).limit(capped * 5)
        if tenant_id is not None:
            stmt = stmt.where(Run.tenant_id == tenant_id)
        rows = list((await self.session.scalars(stmt)).all())
        matched = [
            run
            for run in rows
            if isinstance(run.metadata_, dict)
            and isinstance(run.metadata_.get(INTERNAL_METADATA_KEY), dict)
            and run.metadata_[INTERNAL_METADATA_KEY].get("schedule_id") == schedule_id
        ]
        return matched[:capped]

    async def fire_due_schedules(self, *, limit: int = 50) -> dict[str, int]:
        """Claim due schedules and enqueue Runs. Used by the worker sweeper."""
        now = datetime.now(UTC)
        capped = max(1, min(limit, 200))
        stmt = (
            select(RunSchedule)
            .where(RunSchedule.enabled.is_(True), RunSchedule.next_run_at <= now)
            .order_by(RunSchedule.next_run_at.asc())
            .limit(capped)
            .with_for_update(skip_locked=True)
        )
        try:
            due = list((await self.session.scalars(stmt)).all())
        except Exception:
            # SQLite / dialects without SKIP LOCKED: fall back to plain select.
            stmt = (
                select(RunSchedule)
                .where(RunSchedule.enabled.is_(True), RunSchedule.next_run_at <= now)
                .order_by(RunSchedule.next_run_at.asc())
                .limit(capped)
            )
            due = list((await self.session.scalars(stmt)).all())

        fired = 0
        run_ids: list[str] = []
        for row in due:
            # Re-check in case of soft races without row locks.
            if not row.enabled or _as_utc(row.next_run_at) > now:
                continue
            # Advance the cursor before creating the Run so concurrent
            # sweepers cannot claim the same fire window.
            self._advance_cursor(row, when=now)
            await self.session.commit()
            run = await self._fire(row, advance=False)
            row.last_run_at = now
            row.last_run_id = run.id
            row.updated_at = utcnow()
            await self.session.commit()
            run_ids.append(run.id)
            fired += 1

        for run_id in run_ids:
            await self.runs.start_run(run_id)
        return {"schedules_fired": fired}

    def _advance_cursor(self, row: RunSchedule, *, when: datetime) -> None:
        try:
            row.next_run_at = next_fire_at(
                cron=row.cron,
                interval_seconds=row.interval_seconds,
                timezone=row.timezone,
                after=when,
            )
        except ScheduleTimingError:
            row.enabled = False
        row.updated_at = utcnow()

    async def _fire(
        self,
        row: RunSchedule,
        *,
        advance: bool,
        claimed_at: datetime | None = None,
    ) -> Run:
        agent = await self.session.get(Agent, row.agent_id)
        if agent is None:
            raise AgentNotFound(row.agent_id)

        run = await self.runs.create_run(
            RunCreate(
                agent_id=row.agent_id,
                input=dict(row.input or {}),
                metadata=_pin_metadata(
                    dict(row.metadata_ or {}),
                    agent_version=agent.version,
                    schedule_id=row.id,
                ),
                adapter=row.adapter,
            ),
            tenant_id=row.tenant_id,
            project_id=row.project_id,
        )
        if advance:
            when = claimed_at or datetime.now(UTC)
            row.last_run_at = when
            row.last_run_id = run.id
            self._advance_cursor(row, when=when)
        return run

    async def _require(
        self,
        schedule_id: str,
        *,
        tenant_id: str | None,
        project_id: str | None,
        agent_id: str | None,
    ) -> RunSchedule:
        row = await self.session.get(RunSchedule, schedule_id)
        if (
            row is None
            or (tenant_id is not None and row.tenant_id != tenant_id)
            or (project_id is not None and row.project_id != project_id)
            or (agent_id is not None and row.agent_id != agent_id)
        ):
            raise ScheduleNotFound(schedule_id)
        return row

    async def _require_agent(
        self,
        agent_id_value: str,
        *,
        tenant_id: str | None,
        project_id: str | None,
        agent_id: str | None,
    ) -> Agent:
        agent = await self.session.get(Agent, agent_id_value)
        if (
            agent is None
            or (tenant_id is not None and agent.tenant_id != tenant_id)
            or (project_id is not None and agent.project_id != project_id)
            or (agent_id is not None and agent.id != agent_id)
        ):
            raise AgentNotFound(agent_id_value)
        return agent

    @staticmethod
    def _normalize_timing(
        *,
        cron: str | None,
        interval_seconds: int | None,
        timezone: str,
    ) -> tuple[str | None, int | None]:
        if (cron is None or cron == "") == (interval_seconds is None):
            raise ScheduleValidationError(
                "Provide exactly one of cron or interval_seconds"
            )
        if cron:
            try:
                return validate_cron(cron, timezone=timezone), None
            except ScheduleTimingError as exc:
                raise ScheduleValidationError(str(exc)) from exc
        assert interval_seconds is not None
        try:
            return None, validate_interval(interval_seconds)
        except ScheduleTimingError as exc:
            raise ScheduleValidationError(str(exc)) from exc
