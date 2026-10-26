"""Tests for runtime model routing / fallback."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.runtime.model_router import (
    ModelRoutingExhaustedError,
    classify_provider_error,
    invoke_with_fallback,
    parse_model_routing,
)


def test_parse_model_routing_defaults():
    cfg = parse_model_routing({})
    assert cfg.primary == "openai/gpt-4o-mini"
    assert cfg.fallbacks == ()
    assert cfg.chain() == ["openai/gpt-4o-mini"]
    assert cfg.max_attempts_per_model == 1


def test_parse_model_routing_nested_and_shorthand():
    cfg = parse_model_routing(
        {
            "model": "openai/gpt-4o",
            "model_routing": {
                "fallbacks": ["openai/gpt-4o-mini", "openai/gpt-4o"],
                "max_attempts_per_model": 2,
                "retry_on": ["rate_limit", "server_error"],
            },
        }
    )
    assert cfg.primary == "openai/gpt-4o"
    # primary de-duped from fallbacks in chain()
    assert cfg.chain() == ["openai/gpt-4o", "openai/gpt-4o-mini"]
    assert cfg.max_attempts_per_model == 2
    assert cfg.retry_on == frozenset({"rate_limit", "server_error"})

    shorthand = parse_model_routing(
        {
            "model": "openai/a",
            "fallback_models": ["openai/b", "openai/a"],
        }
    )
    assert shorthand.chain() == ["openai/a", "openai/b"]


def test_parse_model_routing_primary_override():
    cfg = parse_model_routing(
        {"model": "openai/default", "fallback_models": ["openai/fb"]},
        primary="openai/node-model",
    )
    assert cfg.primary == "openai/node-model"
    assert cfg.chain() == ["openai/node-model", "openai/fb"]


def test_classify_provider_error_http_status():
    request = httpx.Request("POST", "https://example.com/v1/chat")
    response_429 = httpx.Response(429, request=request)
    exc_429 = httpx.HTTPStatusError("rate", request=request, response=response_429)
    assert classify_provider_error(exc_429) == "rate_limit"

    response_500 = httpx.Response(500, request=request)
    exc_500 = httpx.HTTPStatusError("boom", request=request, response=response_500)
    assert classify_provider_error(exc_500) == "server_error"

    response_400 = httpx.Response(400, request=request)
    exc_400 = httpx.HTTPStatusError("bad", request=request, response=response_400)
    assert classify_provider_error(exc_400) is None

    assert classify_provider_error(httpx.ConnectError("nope", request=request)) == (
        "connection"
    )
    assert classify_provider_error(TimeoutError()) == "timeout"
    assert classify_provider_error(ValueError("bad schema")) is None


@pytest.mark.asyncio
async def test_invoke_with_fallback_succeeds_on_second_model():
    calls: list[str] = []

    async def invoke(model: str) -> str:
        calls.append(model)
        if model == "primary":
            request = httpx.Request("POST", "https://example.com")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError(
                "unavailable", request=request, response=response
            )
        return f"ok:{model}"

    routing = parse_model_routing(
        {"model": "primary", "fallback_models": ["secondary"]}
    )
    fallbacks: list[tuple[str, str]] = []

    async def on_fallback(attempt: Any, next_model: str) -> None:
        fallbacks.append((attempt.model, next_model))

    result, routed = await invoke_with_fallback(
        invoke, routing=routing, on_fallback=on_fallback
    )
    assert result == "ok:secondary"
    assert calls == ["primary", "secondary"]
    assert routed.fell_back is True
    assert routed.model == "secondary"
    assert fallbacks == [("primary", "secondary")]
    assert routed.as_dict()["used"] == "secondary"


@pytest.mark.asyncio
async def test_invoke_with_fallback_does_not_retry_client_errors():
    async def invoke(model: str) -> str:
        request = httpx.Request("POST", "https://example.com")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("auth", request=request, response=response)

    routing = parse_model_routing(
        {"model": "primary", "fallback_models": ["secondary"]}
    )
    with pytest.raises(httpx.HTTPStatusError):
        await invoke_with_fallback(invoke, routing=routing)


@pytest.mark.asyncio
async def test_invoke_with_fallback_exhausted():
    async def invoke(model: str) -> str:
        raise TimeoutError(f"timeout:{model}")

    routing = parse_model_routing(
        {
            "model": "a",
            "model_routing": {
                "fallbacks": ["b"],
                "max_attempts_per_model": 1,
            },
        }
    )
    with pytest.raises(ModelRoutingExhaustedError) as exc_info:
        await invoke_with_fallback(invoke, routing=routing)
    assert [a.model for a in exc_info.value.routing.attempts] == ["a", "b"]
    assert isinstance(exc_info.value.last_error, TimeoutError)


@pytest.mark.asyncio
async def test_invoke_with_fallback_retries_same_model():
    calls: list[str] = []

    async def invoke(model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            raise TimeoutError("once")
        return "ok"

    routing = parse_model_routing(
        {
            "model": "only",
            "model_routing": {"max_attempts_per_model": 2},
        }
    )
    result, routed = await invoke_with_fallback(invoke, routing=routing)
    assert result == "ok"
    assert calls == ["only", "only"]
    assert routed.fell_back is True  # retried after a failure
    assert len(routed.attempts) == 2


@pytest.mark.asyncio
async def test_invoke_with_fallback_propagates_cancel():
    async def invoke(_model: str) -> str:
        raise asyncio.CancelledError()

    routing = parse_model_routing({"model": "a", "fallback_models": ["b"]})
    with pytest.raises(asyncio.CancelledError):
        await invoke_with_fallback(invoke, routing=routing)
