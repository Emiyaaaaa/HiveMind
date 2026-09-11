"""Enforce and accumulate agent-level token / cost quotas."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent
from app.models.quota import AgentQuotaUsage
from app.runtime.quota import (
    QUOTA_APPLIED_KEY,
    AgentQuotaConfig,
    QuotaExceeded,
    QuotaSnapshot,
    delta_snapshots,
    exceeds_quota,
    parse_quota_config,
    period_bounds,
    period_key,
    snapshot_from_mapping,
    snapshot_from_usage,
)
from app.services.agent_versions import INTERNAL_METADATA_KEY


class QuotaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def status_for_agent(self, agent: Agent) -> dict[str, Any]:
        cfg = parse_quota_config(agent.config)
        if cfg is None or not cfg.active:
            return {
                "agent_id": agent.id,
                "active": False,
                "enforce": False,
                "period": None,
                "period_key": None,
                "period_start": None,
                "period_end": None,
                "max_tokens": None,
                "max_cost_usd": None,
                "used_tokens": 0,
                "used_tokens_in": 0,
                "used_tokens_out": 0,
                "used_cost_usd": 0.0,
                "run_count": 0,
                "remaining_tokens": None,
                "remaining_cost_usd": None,
                "exceeded": False,
            }

        key = period_key(cfg.period)
        row = await self._get_row(agent.id, key)
        used = QuotaSnapshot(
            tokens_in=int(row.tokens_in) if row else 0,
            tokens_out=int(row.tokens_out) if row else 0,
            cost_usd=float(row.cost_usd) if row else 0.0,
        )
        reason = exceeds_quota(cfg, used)
        start, end = period_bounds(cfg.period, key)
        remaining_tokens = (
            None
            if cfg.max_tokens is None
            else max(0, cfg.max_tokens - used.tokens)
        )
        remaining_cost = (
            None
            if cfg.max_cost_usd is None
            else max(0.0, round(cfg.max_cost_usd - used.cost_usd, 6))
        )
        return {
            "agent_id": agent.id,
            "active": True,
            "enforce": cfg.enforce,
            "period": cfg.period,
            "period_key": key,
            "period_start": start,
            "period_end": end,
            "max_tokens": cfg.max_tokens,
            "max_cost_usd": cfg.max_cost_usd,
            "used_tokens": used.tokens,
            "used_tokens_in": used.tokens_in,
            "used_tokens_out": used.tokens_out,
            "used_cost_usd": round(used.cost_usd, 6),
            "run_count": int(row.run_count) if row else 0,
            "remaining_tokens": remaining_tokens,
            "remaining_cost_usd": remaining_cost,
            "exceeded": reason is not None,
        }

    async def assert_can_create_run(self, agent: Agent) -> None:
        cfg = parse_quota_config(agent.config)
        if cfg is None or not cfg.active or not cfg.enforce:
            return
        key = period_key(cfg.period)
        row = await self._get_row(agent.id, key, for_update=True)
        used = QuotaSnapshot(
            tokens_in=int(row.tokens_in) if row else 0,
            tokens_out=int(row.tokens_out) if row else 0,
            cost_usd=float(row.cost_usd) if row else 0.0,
        )
        reason = exceeds_quota(cfg, used)
        if reason is None:
            return
        raise QuotaExceeded(
            agent_id=agent.id,
            period_key=key,
            reason=reason,
            used_tokens=used.tokens,
            max_tokens=cfg.max_tokens,
            used_cost_usd=used.cost_usd,
            max_cost_usd=cfg.max_cost_usd,
        )

    async def apply_run_usage(
        self,
        *,
        agent: Agent,
        run_metadata: dict[str, Any] | None,
        usage: Any,
    ) -> dict[str, Any]:
        """Credit period counters with the delta since the last applied usage.

        Returns the (possibly updated) run metadata that should be persisted.
        """
        cfg = parse_quota_config(agent.config)
        meta = dict(run_metadata or {})
        if cfg is None or not cfg.active:
            return meta

        current = snapshot_from_usage(usage)
        if current.tokens == 0 and current.cost_usd == 0.0:
            return meta

        key = period_key(cfg.period)
        previous, prev_key = _read_applied(meta)
        if prev_key == key:
            delta = delta_snapshots(previous, current)
        else:
            # New period bucket (or first apply): credit the full current totals.
            delta = current
        if delta.tokens == 0 and delta.cost_usd == 0.0:
            return meta

        row = await self._get_or_create_row(agent, cfg, key)
        row.tokens_in = int(row.tokens_in) + delta.tokens_in
        row.tokens_out = int(row.tokens_out) + delta.tokens_out
        row.cost_usd = round(float(row.cost_usd) + delta.cost_usd, 6)
        if previous.tokens == 0 and previous.cost_usd == 0.0:
            row.run_count = int(row.run_count) + 1

        internal = dict(meta.get(INTERNAL_METADATA_KEY) or {})
        if not isinstance(internal, dict):
            internal = {}
        applied = current.as_dict()
        applied["period_key"] = key
        internal[QUOTA_APPLIED_KEY] = applied
        meta[INTERNAL_METADATA_KEY] = internal
        return meta


    async def _get_row(
        self, agent_id: str, key: str, *, for_update: bool = False
    ) -> AgentQuotaUsage | None:
        stmt = select(AgentQuotaUsage).where(
            AgentQuotaUsage.agent_id == agent_id,
            AgentQuotaUsage.period_key == key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_row(
        self, agent: Agent, cfg: AgentQuotaConfig, key: str
    ) -> AgentQuotaUsage:
        row = await self._get_row(agent.id, key, for_update=True)
        if row is not None:
            return row
        row = AgentQuotaUsage(
            tenant_id=agent.tenant_id,
            agent_id=agent.id,
            period=cfg.period,
            period_key=key,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            run_count=0,
        )
        self.session.add(row)
        await self.session.flush()
        return row


def _read_applied(metadata: dict[str, Any]) -> tuple[QuotaSnapshot, str | None]:
    internal = metadata.get(INTERNAL_METADATA_KEY)
    if not isinstance(internal, dict):
        return QuotaSnapshot(), None
    raw = internal.get(QUOTA_APPLIED_KEY)
    if not isinstance(raw, dict):
        return QuotaSnapshot(), None
    return snapshot_from_mapping(raw), (
        str(raw["period_key"]) if raw.get("period_key") else None
    )
