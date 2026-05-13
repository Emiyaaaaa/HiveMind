"""Shared test fixtures.

Tests run against an in-process SQLite database via aiosqlite, no Postgres
required. The event bus is the in-memory implementation by default.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault(
    "AGENTFLOW_DATABASE_URL", "sqlite+aiosqlite:///:memory:"
)
os.environ.pop("AGENTFLOW_REDIS_URL", None)

# Reset cached settings so the env vars above are honoured.
from app.core.config import get_settings

get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        async with app.router.lifespan_context(app):
            yield ac
