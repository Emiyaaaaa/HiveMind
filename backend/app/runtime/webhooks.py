"""Outbound webhooks for run lifecycle events.

Why this exists: the SSE stream (``GET /v1/events/{run_id}``) needs a client
to hold one connection per run. Integrations that only care that "run X
finished / is waiting for approval" (CI bots, ticketing, chat alerts, pager for
``waiting_human``) need a push instead. This module POSTs the terminal
``RunEvent`` to statically configured URLs.

Delivery contract (mirrored in docs/api-contract.md, "Outbound webhooks"):

- Body is byte-for-byte the SSE frame JSON: ``{type, run_id, at, data}``.
- Headers: ``X-AgentFlow-Event`` (event type), ``X-AgentFlow-Delivery``
  (ULID, stable across retries so receivers can de-duplicate) and, when a
  secret is configured, ``X-AgentFlow-Signature: sha256=<hex HMAC of body>``.
- Any 2xx counts as delivered. Other statuses and transport errors are
  retried with exponential backoff (0.5s, 1s, 2s, ...) up to
  ``webhook_max_attempts``; after that the delivery is logged and dropped.

Delivery is fire-and-forget from the run's point of view: a slow receiver
must never delay or fail the run, so ``dispatch`` schedules a task and
returns. ``drain`` exists so the worker can flush in-flight deliveries on
shutdown and tests can await them deterministically.

ponytail: subscribers are process-wide env config (``AGENTFLOW_WEBHOOK_URLS``),
not a per-tenant table. Upgrade to a ``webhook_subscriptions`` table plus a
Java ``/v1/webhooks`` API when tenants need to self-manage endpoints or
filter by agent; the delivery/signature contract here stays the same.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Awaitable, Callable
from functools import lru_cache

import httpx
from ulid import ULID

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.run import RunEvent

logger = get_logger("webhooks")

# Only run-level outcome events go out; step/message/token events are far too
# chatty for HTTP push and already have SSE + persisted rows.
WEBHOOK_EVENT_TYPES: frozenset[str] = frozenset(
    {"run.completed", "run.failed", "run.cancelled", "run.waiting_human"}
)

SIGNATURE_HEADER = "X-AgentFlow-Signature"
EVENT_HEADER = "X-AgentFlow-Event"
DELIVERY_HEADER = "X-AgentFlow-Delivery"

_BACKOFF_BASE_SECONDS = 0.5


def parse_webhook_urls(raw: str) -> list[str]:
    """Split the comma-separated env value; blanks and duplicates dropped."""
    seen: list[str] = []
    for part in raw.split(","):
        url = part.strip()
        if url and url not in seen:
            seen.append(url)
    return seen


def sign_body(secret: str, body: bytes) -> str:
    """``sha256=<hex>`` HMAC over the raw request body (same scheme as GitHub)."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class WebhookDispatcher:
    def __init__(
        self,
        *,
        urls: list[str],
        secret: str | None = None,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.urls = urls
        self.secret = secret
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self._client = client
        self._sleep = sleep
        # asyncio only keeps weak refs to tasks; hold them so a delivery is not
        # garbage-collected mid-flight.
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.urls)

    def dispatch(self, event: RunEvent) -> asyncio.Task[None] | None:
        """Schedule delivery in the background; returns the task (or None)."""
        if not self.enabled or event.type not in WEBHOOK_EVENT_TYPES:
            return None
        task = asyncio.create_task(self.deliver(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def drain(self) -> None:
        """Wait for every in-flight delivery (worker shutdown, tests)."""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        await self.drain()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def deliver(self, event: RunEvent) -> None:
        """Deliver one event to every configured URL (concurrently)."""
        body = event.model_dump_json().encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            EVENT_HEADER: event.type,
            DELIVERY_HEADER: str(ULID()),
        }
        if self.secret:
            headers[SIGNATURE_HEADER] = sign_body(self.secret, body)
        await asyncio.gather(*(self._deliver_one(url, body, headers, event) for url in self.urls))

    async def _deliver_one(
        self, url: str, body: bytes, headers: dict[str, str], event: RunEvent
    ) -> bool:
        client = self._get_client()
        failure = "unknown"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await client.post(url, content=body, headers=headers)
            except httpx.HTTPError as exc:
                failure = f"{type(exc).__name__}: {exc}"
            else:
                if 200 <= response.status_code < 300:
                    logger.info(
                        "webhook.delivered",
                        url=url,
                        event_type=event.type,
                        run_id=event.run_id,
                        attempt=attempt,
                    )
                    return True
                failure = f"HTTP {response.status_code}"
            if attempt < self.max_attempts:
                delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "webhook.retry",
                    url=url,
                    event_type=event.type,
                    run_id=event.run_id,
                    attempt=attempt,
                    reason=failure,
                    delay=delay,
                )
                await self._sleep(delay)
        logger.error(
            "webhook.dropped",
            url=url,
            event_type=event.type,
            run_id=event.run_id,
            attempts=self.max_attempts,
            reason=failure,
        )
        return False

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client


@lru_cache
def get_webhook_dispatcher() -> WebhookDispatcher:
    """Process-wide dispatcher built from settings (cached like ``get_settings``)."""
    settings = get_settings()
    return WebhookDispatcher(
        urls=parse_webhook_urls(settings.webhook_urls),
        secret=settings.webhook_secret or None,
        timeout_seconds=settings.webhook_timeout_seconds,
        max_attempts=settings.webhook_max_attempts,
    )
