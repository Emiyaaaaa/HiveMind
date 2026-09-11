"""Agent-level token / cost quota policy.

Limits live on ``Agent.config`` so they version with the agent definition::

    {
      "quota": {
        "period": "month",          # "day" | "week" | "month"
        "max_tokens": 1_000_000,    # tokens_in + tokens_out; omit = unlimited
        "max_cost_usd": 25.0,       # omit = unlimited
        "enforce": true             # false = track only, never block
      }
    }

When neither ``max_tokens`` nor ``max_cost_usd`` is set the quota is inactive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

PeriodName = Literal["day", "week", "month"]
QUOTA_APPLIED_KEY = "quota_applied"


@dataclass(frozen=True)
class AgentQuotaConfig:
    period: PeriodName = "month"
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    enforce: bool = True

    @property
    def active(self) -> bool:
        return self.max_tokens is not None or self.max_cost_usd is not None


@dataclass(frozen=True)
class QuotaSnapshot:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    @property
    def tokens(self) -> int:
        return int(self.tokens_in) + int(self.tokens_out)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tokens_in": int(self.tokens_in),
            "tokens_out": int(self.tokens_out),
            "cost_usd": round(float(self.cost_usd), 6),
        }


class QuotaExceeded(Exception):
    """Raised when creating a run would violate an enforced agent quota."""

    def __init__(
        self,
        *,
        agent_id: str,
        period_key: str,
        reason: str,
        used_tokens: int,
        max_tokens: int | None,
        used_cost_usd: float,
        max_cost_usd: float | None,
    ) -> None:
        self.agent_id = agent_id
        self.period_key = period_key
        self.reason = reason
        self.used_tokens = used_tokens
        self.max_tokens = max_tokens
        self.used_cost_usd = used_cost_usd
        self.max_cost_usd = max_cost_usd
        super().__init__(
            f"Agent quota exceeded ({reason}): period={period_key} "
            f"tokens={used_tokens}"
            + (f"/{max_tokens}" if max_tokens is not None else "")
            + f" cost_usd={used_cost_usd:.6f}"
            + (f"/{max_cost_usd}" if max_cost_usd is not None else "")
        )


def parse_quota_config(config: dict[str, Any] | None) -> AgentQuotaConfig | None:
    """Return a quota config when ``config.quota`` is present; else ``None``."""
    if not config:
        return None
    raw = config.get("quota")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return AgentQuotaConfig()

    period_raw = str(raw.get("period") or "month").strip().lower()
    period: PeriodName
    if period_raw in ("day", "daily"):
        period = "day"
    elif period_raw in ("week", "weekly"):
        period = "week"
    else:
        period = "month"

    max_tokens = _optional_non_negative_int(raw.get("max_tokens"))
    max_cost = _optional_non_negative_float(raw.get("max_cost_usd"))
    enforce = raw.get("enforce", True)
    if isinstance(enforce, str):
        enforce = enforce.strip().lower() not in {"0", "false", "no", "off"}
    else:
        enforce = bool(enforce)

    return AgentQuotaConfig(
        period=period,
        max_tokens=max_tokens,
        max_cost_usd=max_cost,
        enforce=enforce,
    )


def period_key(period: PeriodName, when: datetime | None = None) -> str:
    """UTC period bucket id for durable counters."""
    instant = when or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    else:
        instant = instant.astimezone(UTC)
    day: date = instant.date()
    if period == "day":
        return day.isoformat()
    if period == "week":
        iso = day.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return f"{day.year:04d}-{day.month:02d}"


def period_bounds(period: PeriodName, key: str) -> tuple[datetime, datetime]:
    """Inclusive start / exclusive end (UTC) for a period key."""
    from datetime import timedelta

    if period == "day":
        start = datetime.fromisoformat(key).replace(tzinfo=UTC)
        return start, start + timedelta(days=1)
    if period == "week":
        year_s, week_s = key.split("-W", 1)
        year, week = int(year_s), int(week_s)
        start = date.fromisocalendar(year, week, 1)
        start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
        return start_dt, start_dt + timedelta(days=7)
    year_s, month_s = key.split("-", 1)
    year, month = int(year_s), int(month_s)
    start_dt = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end_dt = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end_dt = datetime(year, month + 1, 1, tzinfo=UTC)
    return start_dt, end_dt


def exceeds_quota(cfg: AgentQuotaConfig, used: QuotaSnapshot) -> str | None:
    """Return a short reason if ``used`` is at/over any configured limit."""
    if cfg.max_tokens is not None and used.tokens >= cfg.max_tokens:
        return "tokens"
    if cfg.max_cost_usd is not None and used.cost_usd >= cfg.max_cost_usd:
        return "cost_usd"
    return None


def snapshot_from_usage(usage: Any) -> QuotaSnapshot:
    return QuotaSnapshot(
        tokens_in=int(getattr(usage, "tokens_in", 0) or 0),
        tokens_out=int(getattr(usage, "tokens_out", 0) or 0),
        cost_usd=float(getattr(usage, "cost_usd", 0.0) or 0.0),
    )


def snapshot_from_mapping(raw: dict[str, Any] | None) -> QuotaSnapshot:
    if not raw:
        return QuotaSnapshot()
    return QuotaSnapshot(
        tokens_in=int(raw.get("tokens_in") or 0),
        tokens_out=int(raw.get("tokens_out") or 0),
        cost_usd=float(raw.get("cost_usd") or 0.0),
    )


def delta_snapshots(previous: QuotaSnapshot, current: QuotaSnapshot) -> QuotaSnapshot:
    return QuotaSnapshot(
        tokens_in=max(0, current.tokens_in - previous.tokens_in),
        tokens_out=max(0, current.tokens_out - previous.tokens_out),
        cost_usd=max(0.0, round(current.cost_usd - previous.cost_usd, 6)),
    )


def _optional_non_negative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _optional_non_negative_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
