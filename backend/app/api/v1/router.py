from fastapi import APIRouter

from app.api.v1 import agents, events, health, projects, retention, runs

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(agents.router)
api_router.include_router(runs.router)
api_router.include_router(retention.router)
api_router.include_router(events.router)
