"""Tenant-scoped data retention and GDPR-style erasure.

Working memory (L0) lives in ``Message`` and ``Checkpoint`` rows. This service
is the single place that deletes them so future ``MemoryItem`` tables can hook
the same paths instead of becoming audit blind spots.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.events import EventBus
from app.models import Checkpoint, Message, Run, RunStatus
from app.runtime.resume_context import without_resume_metadata
from app.services.run_service import RunNotFound

logger = get_logger("retention")


class MemoryErasureHook(Protocol):
    """Extension point for future L1–L3 memory tables (``MemoryItem``, threads)."""

    async def erase_run(self, session: AsyncSession, run: Run) -> dict[str, int]: ...

    async def erase_tenant(
        self, session: AsyncSession, tenant_id: str
    ) -> dict[str, int]: ...


_memory_erasure_hooks: list[MemoryErasureHook] = []


def register_memory_erasure_hook(hook: MemoryErasureHook) -> None:
    _memory_erasure_hooks.append(hook)


class RetentionService:
    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.bus = bus
        self.settings = settings or get_settings()

    async def erase_run_data(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, int]:
        run = await self._get_run(
            run_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        if run.status in {RunStatus.PENDING, RunStatus.RUNNING}:
            raise RunConflictForErase(run_id, run.status)

        counts = await self._erase_run_rows(run)
        await self._clear_run_transcript_fields(run)
        await self.bus.delete_run_log(run_id)
        await self.session.commit()

        logger.info(
            "retention.run_erased",
            run_id=run_id,
            tenant_id=run.tenant_id,
            **counts,
        )
        return {"messages_deleted": counts["messages"], "checkpoints_deleted": counts["checkpoints"]}

    async def erase_tenant_data(self, tenant_id: str) -> dict[str, int]:
        stmt = select(Run.id).where(Run.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        run_ids = list(result.scalars().all())

        total_messages = 0
        total_checkpoints = 0
        for run_id in run_ids:
            run = await self.session.get(Run, run_id)
            if run is None:
                continue
            counts = await self._erase_run_rows(run)
            await self._clear_run_transcript_fields(run)
            await self.bus.delete_run_log(run_id)
            total_messages += counts["messages"]
            total_checkpoints += counts["checkpoints"]

        hook_totals = await self._invoke_tenant_hooks(tenant_id)
        await self.session.commit()

        logger.info(
            "retention.tenant_erased",
            tenant_id=tenant_id,
            runs_processed=len(run_ids),
            messages_deleted=total_messages,
            checkpoints_deleted=total_checkpoints,
            **hook_totals,
        )
        return {
            "runs_processed": len(run_ids),
            "messages_deleted": total_messages,
            "checkpoints_deleted": total_checkpoints,
            **hook_totals,
        }

    async def purge_expired(
        self,
        *,
        tenant_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        ttl_days = self.settings.data_retention_tenant_ttl_days
        if ttl_days <= 0:
            return {
                "runs_purged": 0,
                "messages_deleted": 0,
                "checkpoints_deleted": 0,
            }

        cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        tenants = [tenant_id] if tenant_id else await self._distinct_tenant_ids()

        runs_purged = 0
        total_messages = 0
        total_checkpoints = 0

        for tid in tenants:
            stmt = (
                select(Run)
                .where(
                    Run.tenant_id == tid,
                    Run.created_at < cutoff,
                    Run.status.in_(
                        [
                            RunStatus.SUCCEEDED,
                            RunStatus.FAILED,
                            RunStatus.CANCELLED,
                        ]
                    ),
                )
                .order_by(Run.created_at.asc())
                .limit(self.settings.data_retention_purge_batch_size)
            )
            result = await self.session.execute(stmt)
            runs = list(result.scalars().all())

            for run in runs:
                if dry_run:
                    msg_count = await self._count_messages(run.id)
                    cp_count = await self._count_checkpoints(run.id)
                else:
                    counts = await self._erase_run_rows(run)
                    await self._clear_run_transcript_fields(run)
                    await self.bus.delete_run_log(run.id)
                    msg_count = counts["messages"]
                    cp_count = counts["checkpoints"]
                runs_purged += 1
                total_messages += msg_count
                total_checkpoints += cp_count

        if not dry_run:
            await self.session.commit()

        if runs_purged:
            logger.info(
                "retention.ttl_purge",
                tenant_id=tenant_id or "*",
                runs_purged=runs_purged,
                messages_deleted=total_messages,
                checkpoints_deleted=total_checkpoints,
                dry_run=dry_run,
            )

        return {
            "runs_purged": runs_purged,
            "messages_deleted": total_messages,
            "checkpoints_deleted": total_checkpoints,
        }

    async def _erase_run_rows(self, run: Run) -> dict[str, int]:
        msg_result = await self.session.execute(
            delete(Message).where(Message.run_id == run.id)
        )
        cp_result = await self.session.execute(
            delete(Checkpoint).where(Checkpoint.run_id == run.id)
        )
        hook_counts: dict[str, int] = {}
        for hook in _memory_erasure_hooks:
            extra = await hook.erase_run(self.session, run)
            for key, value in extra.items():
                hook_counts[key] = hook_counts.get(key, 0) + int(value)
        return {
            "messages": int(msg_result.rowcount or 0),
            "checkpoints": int(cp_result.rowcount or 0),
            **hook_counts,
        }

    async def _clear_run_transcript_fields(self, run: Run) -> None:
        run.output = None
        run.metadata_ = without_resume_metadata(run.metadata_)

    async def _invoke_tenant_hooks(self, tenant_id: str) -> dict[str, int]:
        totals: dict[str, int] = {}
        for hook in _memory_erasure_hooks:
            extra = await hook.erase_tenant(self.session, tenant_id)
            for key, value in extra.items():
                totals[key] = totals.get(key, 0) + int(value)
        return totals

    async def _get_run(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> Run:
        run = await self.session.get(Run, run_id)
        if run is None:
            raise RunNotFound(run_id)
        if tenant_id is not None and run.tenant_id != tenant_id:
            raise RunNotFound(run_id)
        if project_id is not None and run.project_id != project_id:
            raise RunNotFound(run_id)
        if agent_id is not None and run.agent_id != agent_id:
            raise RunNotFound(run_id)
        return run

    async def _distinct_tenant_ids(self) -> list[str]:
        stmt = select(Run.tenant_id).distinct()
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _count_messages(self, run_id: str) -> int:
        stmt = select(func.count()).select_from(Message).where(Message.run_id == run_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def _count_checkpoints(self, run_id: str) -> int:
        stmt = select(func.count()).select_from(Checkpoint).where(Checkpoint.run_id == run_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class RunConflictForErase(Exception):
    def __init__(self, run_id: str, status: RunStatus) -> None:
        self.run_id = run_id
        self.status = status
        super().__init__(
            f"Cannot erase run {run_id} memory while status is {status.value}"
        )
