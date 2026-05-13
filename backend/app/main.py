"""FastAPI entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.adapters import (  # noqa: F401 -- registers built-in adapters as a side effect
    EchoAdapter,
    LangGraphAdapter,
)
from app.api.v1.router import api_router
from app.core.logging import get_logger, setup_logging
from app.db.base import Base
from app.db.session import engine
from app.events import get_event_bus

setup_logging()
logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables exist for SQLite dev mode. In production with Postgres,
    # `alembic upgrade head` is the source of truth.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    bus = get_event_bus()
    logger.info("agentflow.startup", version=__version__)
    try:
        yield
    finally:
        await bus.aclose()
        await engine.dispose()


app = FastAPI(
    title="AgentFlow",
    version=__version__,
    description="Open-source multi-agent runtime.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "agentflow", "version": __version__, "docs": "/docs"}
