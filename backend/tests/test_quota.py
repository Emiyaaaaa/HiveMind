"""Agent-level token / cost quota."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.runtime.quota import (
    QuotaExceeded,
    QuotaSnapshot,
    delta_snapshots,
    exceeds_quota,
    parse_quota_config,
    period_bounds,
    period_key,
)


def test_parse_quota_config_inactive_without_limits():
    assert parse_quota_config({}) is None
    cfg = parse_quota_config({"quota": {"period": "day"}})
    assert cfg is not None
    assert not cfg.active
    assert cfg.period == "day"


def test_parse_quota_config_limits_and_shorthand_period():
    cfg = parse_quota_config(
        {
            "quota": {
                "period": "weekly",
                "max_tokens": 1000,
                "max_cost_usd": 1.5,
                "enforce": "false",
            }
        }
    )
    assert cfg is not None
    assert cfg.active
    assert cfg.period == "week"
    assert cfg.max_tokens == 1000
    assert cfg.max_cost_usd == 1.5
    assert cfg.enforce is False


def test_period_key_and_bounds():
    when = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)
    assert period_key("day", when) == "2026-09-11"
    assert period_key("month", when) == "2026-09"
    week = period_key("week", when)
    assert week.startswith("2026-W")
    start, end = period_bounds("month", "2026-09")
    assert start == datetime(2026, 9, 1, tzinfo=UTC)
    assert end == datetime(2026, 10, 1, tzinfo=UTC)


def test_exceeds_and_delta():
    cfg = parse_quota_config({"quota": {"max_tokens": 10, "max_cost_usd": 1.0}})
    assert exceeds_quota(cfg, QuotaSnapshot(tokens_in=4, tokens_out=6)) == "tokens"
    assert exceeds_quota(cfg, QuotaSnapshot(cost_usd=1.0)) == "cost_usd"
    assert exceeds_quota(cfg, QuotaSnapshot(tokens_in=1, cost_usd=0.1)) is None
    delta = delta_snapshots(
        QuotaSnapshot(tokens_in=5, tokens_out=1, cost_usd=0.1),
        QuotaSnapshot(tokens_in=8, tokens_out=3, cost_usd=0.25),
    )
    assert delta == QuotaSnapshot(tokens_in=3, tokens_out=2, cost_usd=0.15)


@pytest.mark.asyncio
async def test_quota_blocks_create_and_tracks_usage(client):
    create = await client.post(
        "/v1/agents",
        json={
            "name": "quota-bot",
            "adapter": "echo",
            "config": {"quota": {"period": "day", "max_tokens": 5, "max_cost_usd": 10}},
        },
    )
    assert create.status_code == 201
    agent_id = create.json()["id"]

    # Seed period usage so the next create is blocked.
    from app.db.session import SessionLocal
    from app.models.quota import AgentQuotaUsage
    from app.runtime.quota import period_key as pk

    async with SessionLocal() as session:
        session.add(
            AgentQuotaUsage(
                tenant_id="default",
                agent_id=agent_id,
                period="day",
                period_key=pk("day"),
                tokens_in=3,
                tokens_out=2,
                cost_usd=0.01,
                run_count=1,
            )
        )
        await session.commit()

    blocked = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "hi"}},
    )
    assert blocked.status_code == 429
    assert "quota exceeded" in blocked.json()["detail"].lower()

    status = await client.get(f"/v1/agents/{agent_id}/quota")
    assert status.status_code == 200
    body = status.json()
    assert body["active"] is True
    assert body["exceeded"] is True
    assert body["used_tokens"] == 5
    assert body["remaining_tokens"] == 0


@pytest.mark.asyncio
async def test_quota_inactive_allows_runs(client):
    create = await client.post(
        "/v1/agents",
        json={"name": "no-quota-bot", "adapter": "echo", "config": {}},
    )
    agent_id = create.json()["id"]
    status = await client.get(f"/v1/agents/{agent_id}/quota")
    assert status.json()["active"] is False

    run = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "hi"}},
    )
    assert run.status_code == 202


@pytest.mark.asyncio
async def test_quota_apply_delta_on_finalize(client):
    """Echo adapter reports no tokens; inject usage via QuotaService."""
    from app.db.session import SessionLocal
    from app.models import Agent
    from app.runtime.usage import RunUsage
    from app.services.quota_service import QuotaService

    create = await client.post(
        "/v1/agents",
        json={
            "name": "track-bot",
            "adapter": "echo",
            "config": {"quota": {"period": "month", "max_tokens": 1000}},
        },
    )
    agent_id = create.json()["id"]
    run = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "x"}},
    )
    assert run.status_code == 202

    async with SessionLocal() as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None
        meta = await QuotaService(session).apply_run_usage(
            agent=agent,
            run_metadata={},
            usage=RunUsage(tokens_in=10, tokens_out=5, cost_usd=0.002),
        )
        await session.commit()
        assert meta["_agentflow"]["quota_applied"]["tokens_in"] == 10

        # Second apply with higher totals only credits the delta.
        meta2 = await QuotaService(session).apply_run_usage(
            agent=agent,
            run_metadata=meta,
            usage=RunUsage(tokens_in=12, tokens_out=8, cost_usd=0.003),
        )
        await session.commit()
        status = await QuotaService(session).status_for_agent(agent)

    assert status["used_tokens_in"] == 12
    assert status["used_tokens_out"] == 8
    assert status["run_count"] == 1
    assert meta2["_agentflow"]["quota_applied"]["tokens_out"] == 8


def test_quota_exceeded_message():
    exc = QuotaExceeded(
        agent_id="a1",
        period_key="2026-09",
        reason="tokens",
        used_tokens=100,
        max_tokens=100,
        used_cost_usd=0.5,
        max_cost_usd=1.0,
    )
    assert "tokens=100/100" in str(exc)
