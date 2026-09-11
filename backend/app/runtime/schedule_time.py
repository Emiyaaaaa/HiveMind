"""Compute the next fire time for cron or interval schedules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


class ScheduleTimingError(ValueError):
    """Invalid cron expression, timezone, or interval."""


MIN_INTERVAL_SECONDS = 60


def resolve_timezone(name: str | None) -> ZoneInfo:
    label = (name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(label)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleTimingError(f"Unknown timezone: {label}") from exc


def validate_cron(expr: str, *, timezone: str = "UTC") -> str:
    cleaned = expr.strip()
    parts = cleaned.split()
    if len(parts) != 5:
        raise ScheduleTimingError(
            "cron must be a 5-field minute expression (min hour dom month dow)"
        )
    tz = resolve_timezone(timezone)
    now = datetime.now(tz)
    try:
        croniter(cleaned, now)
    except (ValueError, KeyError, TypeError) as exc:
        raise ScheduleTimingError(f"Invalid cron expression: {cleaned}") from exc
    return cleaned


def validate_interval(seconds: int) -> int:
    if seconds < MIN_INTERVAL_SECONDS:
        raise ScheduleTimingError(
            f"interval_seconds must be >= {MIN_INTERVAL_SECONDS}"
        )
    return seconds


def next_fire_at(
    *,
    cron: str | None,
    interval_seconds: int | None,
    timezone: str = "UTC",
    after: datetime | None = None,
) -> datetime:
    """Return the next UTC fire time strictly after ``after`` (default now)."""
    if (cron is None) == (interval_seconds is None):
        raise ScheduleTimingError("Provide exactly one of cron or interval_seconds")

    tz = resolve_timezone(timezone)
    base = after or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    local_base = base.astimezone(tz)

    if interval_seconds is not None:
        seconds = validate_interval(interval_seconds)
        return (base + timedelta(seconds=seconds)).astimezone(UTC)

    assert cron is not None
    expr = validate_cron(cron, timezone=timezone)
    itr = croniter(expr, local_base)
    nxt = itr.get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=tz)
    return nxt.astimezone(UTC)
