"""Runtime model routing and provider fallback.

Phase 5: routing lives in the runtime so adapters call through one policy
instead of embedding retry/fallback logic. Agent config::

    {
      "model": "openai/gpt-4o-mini",
      "model_routing": {
        "fallbacks": ["openai/gpt-4o", "openai/gpt-3.5-turbo"],
        "max_attempts_per_model": 1,
        "retry_on": ["timeout", "rate_limit", "server_error", "connection"]
      }
    }

Shorthand ``fallback_models`` is accepted at the agent-config root and merged
into ``model_routing.fallbacks`` when the nested key is absent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_RETRY_ON = frozenset(
    {"timeout", "rate_limit", "server_error", "connection"}
)
RETRY_KINDS = frozenset(
    {"timeout", "rate_limit", "server_error", "connection", "provider_error"}
)


@dataclass(frozen=True)
class ModelRoutingConfig:
    primary: str = DEFAULT_MODEL
    fallbacks: tuple[str, ...] = ()
    max_attempts_per_model: int = 1
    retry_on: frozenset[str] = DEFAULT_RETRY_ON

    def chain(self) -> list[str]:
        """Primary then fallbacks, de-duplicated while preserving order."""
        seen: set[str] = set()
        ordered: list[str] = []
        for model in (self.primary, *self.fallbacks):
            name = (model or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        return ordered or [DEFAULT_MODEL]


@dataclass
class ModelAttempt:
    model: str
    attempt: int
    error: str | None = None
    error_kind: str | None = None


@dataclass
class RoutedCallResult:
    """Outcome of ``invoke_with_fallback`` (success or exhausted)."""

    model: str
    attempts: list[ModelAttempt] = field(default_factory=list)
    fell_back: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "primary": self.attempts[0].model if self.attempts else self.model,
            "used": self.model,
            "fell_back": self.fell_back,
            "attempts": [
                {
                    "model": a.model,
                    "attempt": a.attempt,
                    "error": a.error,
                    "error_kind": a.error_kind,
                }
                for a in self.attempts
            ],
        }


class ModelRoutingExhaustedError(Exception):
    """Raised when every model in the chain fails with a retryable error."""

    def __init__(
        self,
        *,
        routing: RoutedCallResult,
        last_error: BaseException,
    ) -> None:
        self.routing = routing
        self.last_error = last_error
        models = [a.model for a in routing.attempts]
        super().__init__(
            f"model_routing_exhausted: tried={models!r}; last={last_error}"
        )


def parse_model_routing(
    config: dict[str, Any],
    *,
    primary: str | None = None,
    default_model: str = DEFAULT_MODEL,
) -> ModelRoutingConfig:
    """Parse agent (or node-resolved) model + optional routing block."""
    resolved_primary = (
        (primary or "").strip()
        or str(config.get("model") or default_model).strip()
        or default_model
    )

    raw = config.get("model_routing")
    routing: dict[str, Any] = raw if isinstance(raw, dict) else {}

    fallbacks_raw = routing.get("fallbacks")
    if fallbacks_raw is None:
        fallbacks_raw = config.get("fallback_models")
    fallbacks = _normalize_model_list(fallbacks_raw)

    max_attempts = routing.get("max_attempts_per_model", 1)
    try:
        max_attempts = int(max_attempts)
    except (TypeError, ValueError):
        max_attempts = 1
    max_attempts = max(1, min(max_attempts, 5))

    retry_raw = routing.get("retry_on")
    if retry_raw is None:
        retry_on = DEFAULT_RETRY_ON
    else:
        kinds = {
            str(item).strip().lower()
            for item in _as_list(retry_raw)
            if str(item).strip()
        }
        retry_on = frozenset(kinds & RETRY_KINDS) or DEFAULT_RETRY_ON

    return ModelRoutingConfig(
        primary=resolved_primary,
        fallbacks=tuple(fallbacks),
        max_attempts_per_model=max_attempts,
        retry_on=retry_on,
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _normalize_model_list(value: Any) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for item in _as_list(value):
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        models.append(name)
    return models


def classify_provider_error(exc: BaseException) -> str | None:
    """Map a provider/transport exception to a retry kind, or ``None``.

    Returns ``None`` for non-retryable failures (4xx other than 429, ValueError,
    cancellation, etc.).
    """
    if isinstance(exc, asyncio.CancelledError):
        return None
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "timeout"

    # httpx is optional at import time; match by type name + attributes.
    module = type(exc).__module__ or ""
    name = type(exc).__name__

    if "httpx" in module:
        if name == "TimeoutException" or name.endswith("Timeout"):
            return "timeout"
        if name in {"ConnectError", "ConnectTimeout", "NetworkError", "ProxyError"}:
            return "connection"
        if name == "RemoteProtocolError":
            return "connection"
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status is not None:
            return _classify_http_status(int(status))
        if name == "HTTPStatusError":
            return "server_error"

    status = getattr(exc, "status_code", None)
    if status is not None:
        try:
            return _classify_http_status(int(status))
        except (TypeError, ValueError):
            pass

    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "rate limit" in message or "too many requests" in message:
        return "rate_limit"
    if "connection" in message or "temporarily unavailable" in message:
        return "connection"
    return None


def _classify_http_status(status: int) -> str | None:
    if status == 429:
        return "rate_limit"
    if status in {408, 409}:
        return "timeout"
    if 500 <= status <= 599:
        return "server_error"
    # 4xx (except above) are caller / config errors — do not fall back.
    return None


def is_retryable(exc: BaseException, *, retry_on: frozenset[str]) -> bool:
    kind = classify_provider_error(exc)
    return kind is not None and kind in retry_on


async def invoke_with_fallback(
    invoke: Callable[[str], Awaitable[T]],
    *,
    routing: ModelRoutingConfig,
    on_fallback: Callable[[ModelAttempt, str], Awaitable[None] | None] | None = None,
) -> tuple[T, RoutedCallResult]:
    """Try each model in the routing chain until one succeeds.

    ``invoke(model)`` performs a single provider call. Transient errors matching
    ``routing.retry_on`` advance to the next attempt / model. Non-retryable
    errors propagate immediately. If the chain is exhausted, raises
    ``ModelRoutingExhaustedError``.
    """
    chain = routing.chain()
    attempts: list[ModelAttempt] = []
    last_error: BaseException | None = None

    for model_index, model in enumerate(chain):
        for attempt_no in range(1, routing.max_attempts_per_model + 1):
            try:
                result = await invoke(model)
            except BaseException as exc:
                kind = classify_provider_error(exc)
                attempts.append(
                    ModelAttempt(
                        model=model,
                        attempt=attempt_no,
                        error=str(exc),
                        error_kind=kind,
                    )
                )
                last_error = exc
                if kind is None or kind not in routing.retry_on:
                    raise
                # More attempts on this model, or another model left?
                has_more_attempts = attempt_no < routing.max_attempts_per_model
                has_more_models = model_index + 1 < len(chain)
                if not has_more_attempts and not has_more_models:
                    break
                next_model = (
                    model
                    if has_more_attempts
                    else chain[model_index + 1]
                )
                if on_fallback is not None:
                    maybe = on_fallback(attempts[-1], next_model)
                    if maybe is not None:
                        await maybe
                continue

            fell_back = model != chain[0] or len(attempts) > 0
            attempts.append(ModelAttempt(model=model, attempt=attempt_no))
            return result, RoutedCallResult(
                model=model,
                attempts=attempts,
                fell_back=fell_back,
            )

    assert last_error is not None
    routing_result = RoutedCallResult(
        model=chain[-1] if chain else routing.primary,
        attempts=attempts,
        fell_back=len(chain) > 1,
    )
    raise ModelRoutingExhaustedError(routing=routing_result, last_error=last_error)
