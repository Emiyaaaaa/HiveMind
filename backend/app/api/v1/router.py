from fastapi import APIRouter

from app.api.v1 import (
    agents,
    attachments,
    batches,
    events,
    health,
    memories,
    projects,
    retention,
    runs,
    schedules,
    threads,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(agents.router)
api_router.include_router(threads.router)
api_router.include_router(memories.router)
api_router.include_router(attachments.router)
api_router.include_router(runs.router)
api_router.include_router(batches.router)
api_router.include_router(schedules.router)
api_router.include_router(retention.router)
api_router.include_router(events.router)
