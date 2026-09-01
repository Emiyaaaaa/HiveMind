"""Background TTL sweeper for tenant working-memory retention."""

from __future__ import annotations

import asyncio

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.events import get_event_bus
from app.services.retention_service import RetentionService

logger = get_logger("worker.retention")


async def run_retention_sweeper(stop: asyncio.Event, settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    interval = max(60, cfg.data_retention_purge_interval_seconds)

    while not stop.is_set():
        if cfg.data_retention_tenant_ttl_days <= 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=float(interval))
            except TimeoutError:
                pass
            continue

        try:
            async with SessionLocal() as session:
                service = RetentionService(session=session, bus=get_event_bus(), settings=cfg)
                result = await service.purge_expired()
            if result["runs_purged"]:
                logger.info("retention.sweeper_cycle", **result)
        except Exception:
            logger.exception("retention.sweeper_failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=float(interval))
        except TimeoutError:
            pass
