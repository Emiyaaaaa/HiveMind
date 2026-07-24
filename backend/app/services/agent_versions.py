"""Agent version snapshots and config diff helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentVersion


def snapshot_agent(
    agent: Agent,
    *,
    note: str | None = None,
) -> AgentVersion:
    """Build an ``AgentVersion`` row matching the agent's current fields."""
    return AgentVersion(
        agent_id=agent.id,
        version=agent.version,
        description=agent.description,
        adapter=agent.adapter,
        config=dict(agent.config or {}),
        note=note,
    )


async def get_agent_version(
    session: AsyncSession, agent_id: str, version: int
) -> AgentVersion | None:
    result = await session.execute(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.version == version,
        )
    )
    return result.scalar_one_or_none()


async def list_agent_versions(
    session: AsyncSession, agent_id: str
) -> list[AgentVersion]:
    result = await session.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc())
    )
    return list(result.scalars())


def definition_changed(
    agent: Agent,
    *,
    description: str | None,
    adapter: str,
    config: dict[str, Any],
    description_set: bool,
    adapter_set: bool,
    config_set: bool,
) -> bool:
    """Return True when adapter / config / description would change."""
    if description_set and description != agent.description:
        return True
    if adapter_set and adapter != agent.adapter:
        return True
    if config_set and config != (agent.config or {}):
        return True
    return False


def config_diff(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> dict[str, Any]:
    """Shallow-recursive dict diff with dotted paths for nested objects."""
    left = left or {}
    right = right or {}
    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, dict[str, Any]] = {}

    def walk(a: Any, b: Any, path: str) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            keys = set(a) | set(b)
            for key in sorted(keys):
                child = f"{path}.{key}" if path else key
                if key not in a:
                    added[child] = b[key]
                elif key not in b:
                    removed[child] = a[key]
                else:
                    walk(a[key], b[key], child)
            return
        if a != b:
            if path:
                changed[path] = {"from": a, "to": b}
            else:
                changed[""] = {"from": a, "to": b}

    walk(left, right, "")
    return {"added": added, "removed": removed, "changed": changed}


def version_diff(from_ver: AgentVersion, to_ver: AgentVersion) -> dict[str, Any]:
    adapter_change = None
    if from_ver.adapter != to_ver.adapter:
        adapter_change = {"from": from_ver.adapter, "to": to_ver.adapter}
    description_change = None
    if from_ver.description != to_ver.description:
        description_change = {
            "from": from_ver.description,
            "to": to_ver.description,
        }
    return {
        "from_version": from_ver.version,
        "to_version": to_ver.version,
        "adapter": adapter_change,
        "description": description_change,
        "config": config_diff(from_ver.config, to_ver.config),
    }
