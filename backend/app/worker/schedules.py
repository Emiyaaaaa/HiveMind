"""Background sweeper that fires due RunSchedules."""

from __future__ import annotations

import asyncio

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.events import get_event_bus
from app.services.schedule_service import ScheduleService

logger = get_logger("worker.schedules")


async def run_schedule_sweeper(stop: asyncio.Event, settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    interval = max(5, cfg.schedule_sweeper_interval_seconds)

    while not stop.is_set():
        try:
            async with SessionLocal() as session:
                service = ScheduleService(session=session, bus=get_event_bus())
                result = await service.fire_due_schedules(
                    limit=cfg.schedule_sweeper_batch_size
                )
            if result.get("schedules_fired"):
                logger.info("schedule.sweeper_cycle", **result)
        except Exception:
            logger.exception("schedule.sweeper_failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=float(interval))
        except TimeoutError:
            pass
