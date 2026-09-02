"""SSE subscription helpers for GET /v1/events/{run_id}."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlencode

import httpx

TERMINAL_EVENT_TYPES = frozenset(
    {"run.completed", "run.failed", "run.cancelled"},
)


@dataclass(slots=True)
class RunEvent:
    type: str
    run_id: str
    at: str
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RunEvent:
        return cls(
            type=str(payload["type"]),
            run_id=str(payload["run_id"]),
            at=str(payload["at"]),
            data=dict(payload.get("data") or {}),
        )


def _events_url(base_url: str, run_id: str, last_event_id: str | None) -> str:
    path = f"{base_url.rstrip('/')}/v1/events/{run_id}"
    if not last_event_id:
        return path
    return f"{path}?{urlencode({'last_event_id': last_event_id})}"


def _parse_sse_lines(lines: Iterator[str]) -> Iterator[tuple[str | None, str | None, str]]:
    event_type: str | None = None
    event_id: str | None = None
    data_lines: list[str] = []

    for line in lines:
        if line == "":
            if data_lines:
                yield event_id, event_type, "\n".join(data_lines)
            event_type = None
            event_id = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event_type = value
        elif field == "id":
            event_id = value
        elif field == "data":
            data_lines.append(value)


def subscribe_run_events(
    base_url: str,
    run_id: str,
    *,
    api_key: str | None = None,
    last_event_id: str | None = None,
    on_event: Callable[[RunEvent], None] | None = None,
    timeout: float | None = None,
) -> Iterator[RunEvent]:
    """Stream RunEvent frames until a terminal run event is received."""
    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if api_key:
        headers["X-Api-Key"] = api_key
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id

    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "GET",
            _events_url(base_url, run_id, last_event_id),
            headers=headers,
        ) as response:
            response.raise_for_status()
            line_iter = (line.rstrip("\r") for line in response.iter_lines())
            for _, event_type, data in _parse_sse_lines(line_iter):
                if event_type == "ping":
                    continue
                payload = json.loads(data)
                event = RunEvent.from_dict(payload)
                if on_event is not None:
                    on_event(event)
                yield event
                if event.type in TERMINAL_EVENT_TYPES:
                    return
