"""Checkpoint retention and message decoupling service tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.events import get_event_bus
from app.models import Checkpoint, Run
from app.services.run_service import RunService


@pytest.mark.asyncio
async def test_prune_checkpoints_keeps_latest_human_and_pre_failure():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    bus = get_event_bus()
    async with SessionLocal() as session:
        service = RunService(session=session, bus=bus)
        run = Run(
            tenant_id="default",
            agent_id="01AGENT",
            adapter="echo",
            input={"prompt": "x"},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        for idx, state in enumerate(
            [
                {"graph_state": {"completed_nodes": ["a"], "reply": "one"}},
                {
                    "graph_state": {
                        "completed_nodes": ["a", "b"],
                        "reply": "two",
                        "pending_human": "approve",
                    }
                },
                {"graph_state": {"completed_nodes": ["a", "b", "c"], "reply": "three"}},
            ]
        ):
            session.add(
                Checkpoint(run_id=run.id, index=idx, label=f"cp-{idx}", state=state)
            )
        await session.commit()

        await service._retain_latest_checkpoint(run.id, reason="pre_failure")
        await service._prune_checkpoints(run.id, keep_index=2)

        result = await session.execute(
            select(Checkpoint)
            .where(Checkpoint.run_id == run.id)
            .order_by(Checkpoint.index)
        )
        kept = list(result.scalars().all())
        kept_indexes = [cp.index for cp in kept]
        assert kept_indexes == [1, 2]
        assert kept[0].state["graph_state"]["pending_human"] == "approve"
        assert kept[1].index == 2
