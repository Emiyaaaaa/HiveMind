"""Server-Sent Events stream for a run.

Clients subscribe with `GET /v1/events/{run_id}`. The stream stays open
until the run reaches a terminal state (`succeeded`, `failed`, `cancelled`)
or the client disconnects.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.events import EventBus, get_event_bus
from app.schemas.run import RunEvent

router = APIRouter(prefix="/events", tags=["events"])

_TERMINAL_TYPES = {"run.completed", "run.failed", "run.cancelled"}


@router.get("/{run_id}")
async def stream_run_events(
    run_id: str,
    request: Request,
    bus: EventBus = Depends(get_event_bus),
) -> EventSourceResponse:
    async def generator() -> AsyncIterator[dict[str, str]]:
        async with bus.subscribe(run_id) as queue:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    event: RunEvent = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue

                yield {
                    "event": event.type,
                    "data": event.model_dump_json(),
                }

                if event.type in _TERMINAL_TYPES:
                    break

    return EventSourceResponse(generator())
