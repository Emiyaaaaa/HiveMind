"""Server-Sent Events stream for a run.

Clients subscribe with `GET /v1/events/{run_id}`. The stream stays open
until the run reaches a terminal state (`succeeded`, `failed`, `cancelled`)
or the client disconnects.

On reconnect, clients may send the standard `Last-Event-ID` header (or the
`last_event_id` query parameter) to receive any events published while
disconnected before resuming the live stream.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_settings
from app.events import EventBus, get_event_bus
from app.events.bus import is_after
from app.schemas.run import RunEvent

router = APIRouter(prefix="/events", tags=["events"])

_TERMINAL_TYPES = frozenset({"run.completed", "run.failed", "run.cancelled"})

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# Hint browser / polyfill reconnect interval (milliseconds).
_SSE_RETRY_MS = 3_000


def _resolve_last_event_id(request: Request) -> str | None:
    header = request.headers.get("last-event-id")
    if header:
        return header.strip() or None
    query = request.query_params.get("last_event_id")
    if query:
        return query.strip() or None
    return None


def _sse_frame(event_id: str | None, event: RunEvent) -> dict[str, str]:
    frame: dict[str, str] = {
        "event": event.type,
        "data": event.model_dump_json(),
    }
    if event_id:
        frame["id"] = event_id
    return frame


async def _iter_replay(
    bus: EventBus,
    request: Request,
    run_id: str,
    after_id: str | None,
) -> AsyncIterator[tuple[str | None, RunEvent, bool]]:
    """Yield ``(event_id, event, terminal)`` frames from the durable log."""
    async for event_id, event in bus.replay(run_id, after_id):
        if await request.is_disconnected():
            return
        terminal = event.type in _TERMINAL_TYPES
        yield event_id or None, event, terminal
        if terminal:
            return


@router.get("/{run_id}")
async def stream_run_events(
    run_id: str,
    request: Request,
    bus: EventBus = Depends(get_event_bus),
) -> EventSourceResponse:
    after_id = _resolve_last_event_id(request)
    heartbeat = float(get_settings().event_sse_heartbeat_seconds)

    async def generator() -> AsyncIterator[dict[str, str]]:
        yield {"retry": _SSE_RETRY_MS}
        # Immediate heartbeat so clients/proxies know the stream is alive.
        yield {"event": "ping", "data": "{}"}
        last_id = after_id

        async for event_id, event, terminal in _iter_replay(
            bus, request, run_id, after_id
        ):
            yield _sse_frame(event_id, event)
            if event_id:
                last_id = event_id
            if terminal:
                return

        if await request.is_disconnected():
            return

        # Subscribe first, then catch up from the log so frames published
        # between the initial replay and subscribe are not lost.
        async with bus.subscribe(run_id) as queue:
            async for event_id, event, terminal in _iter_replay(
                bus, request, run_id, last_id
            ):
                yield _sse_frame(event_id, event)
                if event_id:
                    last_id = event_id
                if terminal:
                    return

            if await request.is_disconnected():
                return

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event_id, event = await asyncio.wait_for(
                        queue.get(), timeout=heartbeat
                    )
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue

                # Ephemeral frames (empty id) always pass; persisted ids dedupe.
                if event_id and last_id and not is_after(event_id, last_id):
                    continue
                if event_id:
                    last_id = event_id

                yield _sse_frame(event_id or None, event)

                if event.type in _TERMINAL_TYPES:
                    break

    return EventSourceResponse(
        generator(),
        ping=int(heartbeat),
        headers=_SSE_HEADERS,
        media_type="text/event-stream",
    )
