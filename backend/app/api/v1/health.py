from fastapi import APIRouter

from app import __version__
from app.adapters.base import list_adapters

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": __version__,
        "adapters": list_adapters(),
    }
