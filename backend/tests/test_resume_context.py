"""Tests for slim resume metadata and worker-side checkpoint hydration."""

from __future__ import annotations

import pytest

from app.runtime.resume_context import (
    RESUME_META_KEY,
    parse_resume_context,
    resume_metadata,
)


def test_resume_metadata_omits_checkpoint_state():
    meta = resume_metadata(mode="retry", checkpoint_index=3)
    payload = meta[RESUME_META_KEY]
    assert payload == {"mode": "retry", "checkpoint_index": 3}
    assert "checkpoint_state" not in payload


def test_resume_metadata_includes_human_input():
    meta = resume_metadata(
        mode="resume",
        checkpoint_index=1,
        human_input={"route": "approved"},
    )
    payload = meta[RESUME_META_KEY]
    assert payload["human_input"] == {"route": "approved"}
    assert "checkpoint_state" not in payload


def test_parse_resume_context_ignores_inline_checkpoint_state():
    ctx = parse_resume_context(
        {
            RESUME_META_KEY: {
                "mode": "retry",
                "checkpoint_index": 2,
                "checkpoint_state": {"graph_state": {"reply": "old"}},
            }
        }
    )
    assert ctx is not None
    assert ctx.mode == "retry"
    assert ctx.checkpoint_index == 2
    assert ctx.checkpoint_state is None


@pytest.mark.asyncio
async def test_executor_hydrates_checkpoint_from_db():
    from unittest.mock import AsyncMock, MagicMock

    from app.runtime.resume_context import RunResumeContext
    from app.worker.executor import RunExecutor

    checkpoint = MagicMock()
    checkpoint.state = {"graph_state": {"reply": "from-db"}}
    checkpoint.index = 4

    service = MagicMock()
    service.get_checkpoint_by_index = AsyncMock(return_value=checkpoint)
    service._latest_checkpoint = AsyncMock()

    executor = RunExecutor(bus=MagicMock())
    resume_ctx = RunResumeContext(mode="retry", checkpoint_index=4)
    hydrated = await executor._hydrate_resume_checkpoint(
        service, "run-1", resume_ctx
    )

    assert hydrated.checkpoint_state == {"graph_state": {"reply": "from-db"}}
    assert hydrated.checkpoint_index == 4
    service.get_checkpoint_by_index.assert_awaited_once_with("run-1", 4)


@pytest.mark.asyncio
async def test_executor_hydrate_falls_back_to_latest_checkpoint():
    from unittest.mock import AsyncMock, MagicMock

    from app.runtime.resume_context import RunResumeContext
    from app.worker.executor import RunExecutor

    latest = MagicMock()
    latest.state = {"graph_state": {"pending_human": "approve"}}
    latest.index = 7

    service = MagicMock()
    service.get_checkpoint_by_index = AsyncMock(return_value=None)
    service._latest_checkpoint = AsyncMock(return_value=latest)

    executor = RunExecutor(bus=MagicMock())
    resume_ctx = RunResumeContext(mode="resume", checkpoint_index=99)
    hydrated = await executor._hydrate_resume_checkpoint(
        service, "run-1", resume_ctx
    )

    assert hydrated.checkpoint_state == latest.state
    assert hydrated.checkpoint_index == 7
