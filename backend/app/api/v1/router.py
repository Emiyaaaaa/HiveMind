from fastapi import APIRouter

from app.api.v1 import agents, events, health, runs

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(agents.router)
api_router.include_router(runs.router)
api_router.include_router(events.router)
