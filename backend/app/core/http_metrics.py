"""FastAPI middleware that records RED metrics for each HTTP request."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.telemetry import is_enabled, record_http_red


class RedMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not is_enabled():
            return await call_next(request)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            route = request.scope.get("route")
            route_pattern = getattr(route, "path", request.url.path)
            record_http_red(
                method=request.method,
                route=route_pattern,
                status_code=status_code,
                duration_seconds=time.perf_counter() - start,
            )
