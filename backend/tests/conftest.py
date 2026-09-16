"""Shared test fixtures.

Tests run against a throwaway file-backed SQLite database via aiosqlite, no
Postgres required. The event bus is the in-memory implementation by default.

Why a file and not ``:memory:``: SQLAlchemy serves an in-memory aiosqlite URL
from a ``StaticPool``, i.e. one shared connection. The request session and
the executor's per-run session then interleave their transactions on that
single connection, and a ``refresh()`` right after ``commit()`` fails with
"Could not refresh instance" (23 failures on aiosqlite 0.22 / SQLAlchemy
2.0.54). A file gets the normal pool with one connection per session, which
is also what production Postgres does. Set ``AGENTFLOW_DATABASE_URL`` to
override.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_db_dir = tempfile.mkdtemp(prefix="agentflow-tests-")
atexit.register(shutil.rmtree, _db_dir, ignore_errors=True)
os.environ.setdefault(
    "AGENTFLOW_DATABASE_URL", f"sqlite+aiosqlite:///{_db_dir}/agentflow.db"
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
