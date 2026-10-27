"""Enforce and accumulate tenant, project, and agent token / cost quotas."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Project
from app.models.quota import (
    AgentQuotaUsage,
    ProjectQuotaConfig,
    ProjectQuotaUsage,
    TenantQuotaConfig,
    TenantQuotaUsage,
)
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
    quota_config_from_values,
    snapshot_from_mapping,
    snapshot_from_usage,
)
from app.services.agent_versions import INTERNAL_METADATA_KEY


class QuotaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def status_for_agent(self, agent: Agent) -> dict[str, Any]:
        cfg = parse_quota_config(agent.config)
        return await self._status(
            scope="agent",
            scope_id=agent.id,
            tenant_id=agent.tenant_id,
            project_id=agent.project_id,
            agent_id=agent.id,
            cfg=cfg,
            row=await self._usage_row("agent", agent.id, cfg),
        )

    async def status_for_project(self, project: Project) -> dict[str, Any]:
        cfg_row = await self._project_config(project.id)
        cfg = _config_from_row(cfg_row)
        return await self._status(
            scope="project",
            scope_id=project.id,
            tenant_id=project.tenant_id,
            project_id=project.id,
            agent_id=None,
            cfg=cfg,
            row=await self._usage_row("project", project.id, cfg),
        )

    async def status_for_tenant(self, tenant_id: str) -> dict[str, Any]:
        cfg_row = await self._tenant_config(tenant_id)
        cfg = _config_from_row(cfg_row)
        return await self._status(
            scope="tenant",
            scope_id=tenant_id,
            tenant_id=tenant_id,
            project_id=None,
            agent_id=None,
            cfg=cfg,
            row=await self._usage_row("tenant", tenant_id, cfg),
        )

    async def upsert_project_config(
        self, project: Project, payload: dict[str, Any]
    ) -> ProjectQuotaConfig:
        cfg = quota_config_from_values(
            period=payload.get("period"),
            max_tokens=payload.get("max_tokens"),
            max_cost_usd=payload.get("max_cost_usd"),
            enforce=payload.get("enforce", True),
        )
        row = await self._project_config(project.id, for_update=True)
        if row is None:
            row = ProjectQuotaConfig(
                tenant_id=project.tenant_id,
                project_id=project.id,
            )
            self.session.add(row)
        _apply_config(row, cfg)
        await self.session.flush()
        return row

    async def upsert_tenant_config(
        self, tenant_id: str, payload: dict[str, Any]
    ) -> TenantQuotaConfig:
        cfg = quota_config_from_values(
            period=payload.get("period"),
            max_tokens=payload.get("max_tokens"),
            max_cost_usd=payload.get("max_cost_usd"),
            enforce=payload.get("enforce", True),
        )
        row = await self._tenant_config(tenant_id, for_update=True)
        if row is None:
            row = TenantQuotaConfig(tenant_id=tenant_id)
            self.session.add(row)
        _apply_config(row, cfg)
        await self.session.flush()
        return row

    async def assert_can_create_run(self, agent: Agent) -> None:
        """Block when tenant, project, or agent enforced usage is already over."""
        for scope, scope_id, cfg in await self._enforced_scopes(agent):
            key = period_key(cfg.period)
            row = await self._usage_row(scope, scope_id, cfg, for_update=True)
            used = _snapshot(row)
            reason = exceeds_quota(cfg, used)
            if reason is None:
                continue
            raise QuotaExceeded(
                scope=scope,
                scope_id=scope_id,
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
        """Credit every active scope with the delta since the last applied usage.

        Returns the (possibly updated) run metadata that should be persisted.
        """
        meta = dict(run_metadata or {})
        targets = await self._active_scopes(agent)
        if not targets:
            return meta

        current = snapshot_from_usage(usage)
        if current.tokens == 0 and current.cost_usd == 0.0:
            return meta

        previous, applied_raw = _read_applied(meta)
        first_credit = previous.tokens == 0 and previous.cost_usd == 0.0
        scope_keys: dict[str, str] = {}
        credited = False
        for scope, scope_id, cfg in targets:
            key = period_key(cfg.period)
            scope_keys[scope] = key
            prev_key = _applied_period_key(applied_raw, scope)
            delta = delta_snapshots(previous, current) if prev_key == key else current
            if delta.tokens == 0 and delta.cost_usd == 0.0:
                continue
            row = await self._get_or_create_usage(agent, scope, scope_id, cfg, key)
            row.tokens_in = int(row.tokens_in) + delta.tokens_in
            row.tokens_out = int(row.tokens_out) + delta.tokens_out
            row.cost_usd = round(float(row.cost_usd) + delta.cost_usd, 6)
            if first_credit:
                row.run_count = int(row.run_count) + 1
            if scope == "agent":
                row.project_id = agent.project_id
            credited = True

        if not credited and not scope_keys:
            return meta

        internal = dict(meta.get(INTERNAL_METADATA_KEY) or {})
        if not isinstance(internal, dict):
            internal = {}
        applied = current.as_dict()
        applied["period_key"] = scope_keys.get("agent") or next(iter(scope_keys.values()))
        applied["scopes"] = {
            name: {"period_key": key} for name, key in scope_keys.items()
        }
        internal[QUOTA_APPLIED_KEY] = applied
        meta[INTERNAL_METADATA_KEY] = internal
        return meta

    async def _status(
        self,
        *,
        scope: str,
        scope_id: str,
        tenant_id: str,
        project_id: str | None,
        agent_id: str | None,
        cfg: AgentQuotaConfig | None,
        row: Any,
    ) -> dict[str, Any]:
        base = _empty_status(
            scope=scope,
            scope_id=scope_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        if cfg is None or not cfg.active:
            return base

        key = period_key(cfg.period)
        used = _snapshot(row)
        reason = exceeds_quota(cfg, used)
        start, end = period_bounds(cfg.period, key)
        remaining_tokens = (
            None if cfg.max_tokens is None else max(0, cfg.max_tokens - used.tokens)
        )
        remaining_cost = (
            None
            if cfg.max_cost_usd is None
            else max(0.0, round(cfg.max_cost_usd - used.cost_usd, 6))
        )
        base.update(
            {
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
                "run_count": int(getattr(row, "run_count", 0) or 0) if row else 0,
                "remaining_tokens": remaining_tokens,
                "remaining_cost_usd": remaining_cost,
                "exceeded": reason is not None,
            }
        )
        return base

    async def _enforced_scopes(
        self, agent: Agent
    ) -> list[tuple[str, str, AgentQuotaConfig]]:
        return [
            item
            for item in await self._configured_scopes(agent)
            if item[2].active and item[2].enforce
        ]

    async def _active_scopes(
        self, agent: Agent
    ) -> list[tuple[str, str, AgentQuotaConfig]]:
        return [item for item in await self._configured_scopes(agent) if item[2].active]

    async def _configured_scopes(
        self, agent: Agent
    ) -> list[tuple[str, str, AgentQuotaConfig]]:
        scopes: list[tuple[str, str, AgentQuotaConfig]] = []
        tenant_cfg = _config_from_row(await self._tenant_config(agent.tenant_id))
        if tenant_cfg is not None:
            scopes.append(("tenant", agent.tenant_id, tenant_cfg))
        if agent.project_id:
            project_cfg = _config_from_row(await self._project_config(agent.project_id))
            if project_cfg is not None:
                scopes.append(("project", agent.project_id, project_cfg))
        agent_cfg = parse_quota_config(agent.config)
        if agent_cfg is not None:
            scopes.append(("agent", agent.id, agent_cfg))
        return scopes

    async def _usage_row(
        self,
        scope: str,
        scope_id: str,
        cfg: AgentQuotaConfig | None,
        *,
        for_update: bool = False,
    ) -> Any:
        if cfg is None or not cfg.active:
            return None
        key = period_key(cfg.period)
        if scope == "tenant":
            return await self._get_tenant_usage(scope_id, key, for_update=for_update)
        if scope == "project":
            return await self._get_project_usage(scope_id, key, for_update=for_update)
        return await self._get_agent_usage(scope_id, key, for_update=for_update)

    async def _get_or_create_usage(
        self,
        agent: Agent,
        scope: str,
        scope_id: str,
        cfg: AgentQuotaConfig,
        key: str,
    ) -> TenantQuotaUsage | ProjectQuotaUsage | AgentQuotaUsage:
        if scope == "tenant":
            row = await self._get_tenant_usage(scope_id, key, for_update=True)
            if row is None:
                row = TenantQuotaUsage(
                    tenant_id=agent.tenant_id,
                    period=cfg.period,
                    period_key=key,
                )
                self.session.add(row)
                await self.session.flush()
            return row
        if scope == "project":
            row = await self._get_project_usage(scope_id, key, for_update=True)
            if row is None:
                row = ProjectQuotaUsage(
                    tenant_id=agent.tenant_id,
                    project_id=scope_id,
                    period=cfg.period,
                    period_key=key,
                )
                self.session.add(row)
                await self.session.flush()
            return row
        row = await self._get_agent_usage(scope_id, key, for_update=True)
        if row is None:
            row = AgentQuotaUsage(
                tenant_id=agent.tenant_id,
                project_id=agent.project_id,
                agent_id=agent.id,
                period=cfg.period,
                period_key=key,
            )
            self.session.add(row)
            await self.session.flush()
        else:
            row.project_id = agent.project_id
        return row

    async def _tenant_config(
        self, tenant_id: str, *, for_update: bool = False
    ) -> TenantQuotaConfig | None:
        stmt = select(TenantQuotaConfig).where(TenantQuotaConfig.tenant_id == tenant_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _project_config(
        self, project_id: str, *, for_update: bool = False
    ) -> ProjectQuotaConfig | None:
        stmt = select(ProjectQuotaConfig).where(
            ProjectQuotaConfig.project_id == project_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_tenant_usage(
        self, tenant_id: str, key: str, *, for_update: bool = False
    ) -> TenantQuotaUsage | None:
        stmt = select(TenantQuotaUsage).where(
            TenantQuotaUsage.tenant_id == tenant_id,
            TenantQuotaUsage.period_key == key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_project_usage(
        self, project_id: str, key: str, *, for_update: bool = False
    ) -> ProjectQuotaUsage | None:
        stmt = select(ProjectQuotaUsage).where(
            ProjectQuotaUsage.project_id == project_id,
            ProjectQuotaUsage.period_key == key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_agent_usage(
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


def _config_from_row(row: Any) -> AgentQuotaConfig | None:
    if row is None:
        return None
    return quota_config_from_values(
        period=row.period,
        max_tokens=row.max_tokens,
        max_cost_usd=row.max_cost_usd,
        enforce=row.enforce,
    )


def _apply_config(row: Any, cfg: AgentQuotaConfig) -> None:
    row.period = cfg.period
    row.max_tokens = cfg.max_tokens
    row.max_cost_usd = cfg.max_cost_usd
    row.enforce = cfg.enforce


def _snapshot(row: Any) -> QuotaSnapshot:
    if row is None:
        return QuotaSnapshot()
    return QuotaSnapshot(
        tokens_in=int(row.tokens_in or 0),
        tokens_out=int(row.tokens_out or 0),
        cost_usd=float(row.cost_usd or 0.0),
    )


def _empty_status(
    *,
    scope: str,
    scope_id: str,
    tenant_id: str,
    project_id: str | None,
    agent_id: str | None,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "scope_id": scope_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "agent_id": agent_id,
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


def _read_applied(metadata: dict[str, Any]) -> tuple[QuotaSnapshot, dict[str, Any] | None]:
    internal = metadata.get(INTERNAL_METADATA_KEY)
    if not isinstance(internal, dict):
        return QuotaSnapshot(), None
    raw = internal.get(QUOTA_APPLIED_KEY)
    if not isinstance(raw, dict):
        return QuotaSnapshot(), None
    return snapshot_from_mapping(raw), raw


def _applied_period_key(raw: dict[str, Any] | None, scope: str) -> str | None:
    if not raw:
        return None
    scopes = raw.get("scopes")
    if isinstance(scopes, dict):
        entry = scopes.get(scope)
        if isinstance(entry, dict) and entry.get("period_key"):
            return str(entry["period_key"])
    if scope == "agent" and raw.get("period_key"):
        return str(raw["period_key"])
    return None
