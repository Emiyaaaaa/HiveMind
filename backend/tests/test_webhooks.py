"""Outbound webhook delivery: signing, retry/backoff, and run wiring."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.runtime import webhooks
from app.runtime.webhooks import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    WebhookDispatcher,
    get_webhook_dispatcher,
    parse_webhook_urls,
    redact_url,
    sign_body,
)
from app.schemas.run import RunEvent


def _event(event_type: str = "run.completed") -> RunEvent:
    return RunEvent(
        type=event_type,  # type: ignore[arg-type]
        run_id="01HZWEBHOOK000000000000000",
        at=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        data={"output": {"reply": "hi"}},
    )


class _Receiver:
    """Scripted HTTP endpoint: pops one status per call, records requests."""

    def __init__(self, statuses: list[int | Exception]) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.statuses.pop(0) if self.statuses else 200
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome)


def _dispatcher(
    receiver: _Receiver,
    *,
    urls: list[str] | None = None,
    secret: str | None = None,
    max_attempts: int = 3,
) -> tuple[WebhookDispatcher, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    dispatcher = WebhookDispatcher(
        urls=urls or ["http://hook.test/a"],
        secret=secret,
        max_attempts=max_attempts,
        client=httpx.AsyncClient(transport=httpx.MockTransport(receiver.handler)),
        sleep=fake_sleep,
    )
    return dispatcher, sleeps


def test_parse_webhook_urls_trims_blanks_and_duplicates():
    raw = " http://a.test/x, ,http://b.test/y,http://a.test/x "
    assert parse_webhook_urls(raw) == ["http://a.test/x", "http://b.test/y"]
    assert parse_webhook_urls("") == []


@pytest.mark.asyncio
async def test_deliver_posts_signed_sse_frame_to_every_url():
    receiver = _Receiver([200, 200])
    dispatcher, sleeps = _dispatcher(
        receiver, urls=["http://hook.test/a", "http://hook.test/b"], secret="s3cr3t"
    )
    event = _event()

    await dispatcher.deliver(event)

    assert sorted(str(r.url) for r in receiver.requests) == [
        "http://hook.test/a",
        "http://hook.test/b",
    ]
    assert sleeps == []
    first = receiver.requests[0]
    body = first.content
    # Body is the SSE frame verbatim, so receivers can reuse SSE parsers.
    assert json.loads(body) == json.loads(event.model_dump_json())
    assert first.headers["content-type"] == "application/json"
    assert first.headers[EVENT_HEADER] == "run.completed"
    assert len(first.headers[DELIVERY_HEADER]) == 26
    expected = "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    assert first.headers[SIGNATURE_HEADER] == expected
    assert sign_body("s3cr3t", body) == expected
    # Both URLs share one delivery id (same event), which is what a receiver
    # de-duplicates on.
    assert first.headers[DELIVERY_HEADER] == receiver.requests[1].headers[DELIVERY_HEADER]


@pytest.mark.asyncio
async def test_unsigned_when_no_secret():
    receiver = _Receiver([204])
    dispatcher, _ = _dispatcher(receiver)
    await dispatcher.deliver(_event())
    assert SIGNATURE_HEADER not in receiver.requests[0].headers


@pytest.mark.asyncio
async def test_retries_non_2xx_and_transport_errors_with_backoff():
    receiver = _Receiver(
        [500, httpx.ConnectError("refused"), 200],
    )
    dispatcher, sleeps = _dispatcher(receiver, max_attempts=3)
    event = _event("run.failed")

    headers = {EVENT_HEADER: event.type, DELIVERY_HEADER: "01DELIVERYID00000000000000"}
    delivered = await dispatcher._deliver_one("http://hook.test/a", b"{}", headers, event)

    assert delivered is True
    assert len(receiver.requests) == 3
    assert sleeps == [0.5, 1.0]
    # Retries resend the exact same delivery id so receivers can de-duplicate.
    assert {r.headers[DELIVERY_HEADER] for r in receiver.requests} == {"01DELIVERYID00000000000000"}
    assert {r.headers[EVENT_HEADER] for r in receiver.requests} == {"run.failed"}


@pytest.mark.asyncio
async def test_drops_after_max_attempts_without_raising():
    receiver = _Receiver([503, 503])
    dispatcher, sleeps = _dispatcher(receiver, max_attempts=2)
    event = _event("run.cancelled")

    delivered = await dispatcher._deliver_one("http://hook.test/a", b"{}", {}, event)

    assert delivered is False
    assert len(receiver.requests) == 2
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_dispatch_skips_when_disabled_or_non_outcome_event():
    receiver = _Receiver([])
    disabled = WebhookDispatcher(
        urls=[], client=httpx.AsyncClient(transport=httpx.MockTransport(receiver.handler))
    )
    assert disabled.enabled is False
    assert disabled.dispatch(_event()) is None

    enabled, _ = _dispatcher(receiver)
    assert enabled.dispatch(_event("step.started")) is None
    task = enabled.dispatch(_event("run.waiting_human"))
    assert task is not None
    await enabled.drain()
    assert len(receiver.requests) == 1
    assert receiver.requests[0].headers[EVENT_HEADER] == "run.waiting_human"


@pytest.mark.asyncio
async def test_run_finalize_pushes_terminal_and_waiting_human_events(
    monkeypatch: pytest.MonkeyPatch,
):
    """End to end through the API: settings -> dispatcher -> echo run -> POST."""
    monkeypatch.setenv("AGENTFLOW_WEBHOOK_URLS", "http://hook.test/runs")
    monkeypatch.setenv("AGENTFLOW_WEBHOOK_SECRET", "topsecret")
    get_settings.cache_clear()
    get_webhook_dispatcher.cache_clear()

    receiver = _Receiver([])
    dispatcher = get_webhook_dispatcher()
    dispatcher._client = httpx.AsyncClient(transport=httpx.MockTransport(receiver.handler))
    assert dispatcher.urls == ["http://hook.test/runs"]

    from app.main import app

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            async with app.router.lifespan_context(app):
                create = await ac.post(
                    "/v1/agents",
                    json={
                        "name": "hook-bot",
                        "adapter": "echo",
                        "config": {"delay": 0, "pause_before_reply": True},
                    },
                )
                agent_id = create.json()["id"]
                run = await ac.post(
                    "/v1/runs", json={"agent_id": agent_id, "input": {"prompt": "hook"}}
                )
                run_id = run.json()["id"]

                body: dict = {}
                for _ in range(80):
                    body = (await ac.get(f"/v1/runs/{run_id}")).json()
                    if body["status"] == "waiting_human":
                        break
                    await asyncio.sleep(0.05)
                assert body["status"] == "waiting_human", body
                await dispatcher.drain()

                resume = await ac.post(f"/v1/runs/{run_id}/resume", json={"input": {"ok": 1}})
                assert resume.status_code == 202, resume.text
                for _ in range(80):
                    body = (await ac.get(f"/v1/runs/{run_id}")).json()
                    if body["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                    await asyncio.sleep(0.05)
                assert body["status"] == "succeeded", body
                await dispatcher.drain()
    finally:
        get_settings.cache_clear()
        get_webhook_dispatcher.cache_clear()
        os.environ.pop("AGENTFLOW_WEBHOOK_URLS", None)
        os.environ.pop("AGENTFLOW_WEBHOOK_SECRET", None)

    types = [r.headers[EVENT_HEADER] for r in receiver.requests]
    assert types == ["run.waiting_human", "run.completed"]
    payloads = [json.loads(r.content) for r in receiver.requests]
    assert all(p["run_id"] == run_id for p in payloads)
    assert payloads[1]["data"]["output"] == {"reply": "echo: hook"}
    assert payloads[1]["data"]["usage"]["tokens_out"] > 0
    for request in receiver.requests:
        assert request.headers[SIGNATURE_HEADER] == sign_body("topsecret", request.content)
    # Distinct events get distinct delivery ids.
    assert (
        receiver.requests[0].headers[DELIVERY_HEADER]
        != receiver.requests[1].headers[DELIVERY_HEADER]
    )


def test_redact_url_strips_userinfo_query_and_fragment():
    assert (
        redact_url("https://user:tok@hooks.example.com:8443/in/abc?token=s3cr3t#frag")
        == "https://hooks.example.com:8443/in/abc"
    )
    assert redact_url("http://hook.test/a") == "http://hook.test/a"


@pytest.mark.asyncio
async def test_logs_never_contain_the_raw_url(monkeypatch: pytest.MonkeyPatch):
    records: list[dict] = []

    class _Logger:
        def __getattr__(self, _name: str):
            def _log(_event: str, **kw: object) -> None:
                records.append(dict(kw))

            return _log

    monkeypatch.setattr(webhooks, "logger", _Logger())
    receiver = _Receiver([500, 200])
    dispatcher, _ = _dispatcher(receiver, urls=["http://hook.test/in?token=s3cr3t"])

    await dispatcher.deliver(_event())

    assert records, "expected retry + delivered log records"
    assert all("s3cr3t" not in str(r.get("url")) for r in records)
    assert {r["url"] for r in records} == {"http://hook.test/in"}


@pytest.mark.asyncio
async def test_dispatch_sheds_load_beyond_max_pending(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(webhooks, "MAX_PENDING", 2)
    gate = asyncio.Event()

    async def blocked(_request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200)

    dispatcher = WebhookDispatcher(
        urls=["http://hook.test/a"],
        client=httpx.AsyncClient(transport=httpx.MockTransport(blocked)),
    )
    first = dispatcher.dispatch(_event())
    second = dispatcher.dispatch(_event("run.failed"))
    overflow = dispatcher.dispatch(_event("run.cancelled"))
    assert first is not None and second is not None
    assert overflow is None  # dropped, not queued
    gate.set()
    assert await dispatcher.drain() == 0


@pytest.mark.asyncio
async def test_in_flight_requests_are_capped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(webhooks, "MAX_IN_FLIGHT", 2)
    active = 0
    peak = 0

    async def slow(_request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200)

    dispatcher = WebhookDispatcher(
        urls=[f"http://hook.test/{i}" for i in range(6)],
        client=httpx.AsyncClient(transport=httpx.MockTransport(slow)),
    )
    await dispatcher.deliver(_event())
    assert peak == 2


@pytest.mark.asyncio
async def test_aclose_gives_up_after_grace_period():
    async def never(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3600)
        return httpx.Response(200)

    dispatcher = WebhookDispatcher(
        urls=["http://hook.test/a"],
        client=httpx.AsyncClient(transport=httpx.MockTransport(never)),
    )
    task = dispatcher.dispatch(_event())
    assert task is not None

    await asyncio.wait_for(dispatcher.aclose(grace_seconds=0.05), timeout=2)

    assert task.cancelled() or task.done()
    assert dispatcher._tasks == set()


async def _run_to(ac: AsyncClient, run_id: str, statuses: set[str]) -> dict:
    body: dict = {}
    for _ in range(80):
        body = (await ac.get(f"/v1/runs/{run_id}")).json()
        if body["status"] in statuses:
            return body
        await asyncio.sleep(0.05)
    return body


@pytest.mark.asyncio
async def test_run_finalize_pushes_failed_and_cancelled_events(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFLOW_WEBHOOK_URLS", "http://hook.test/runs")
    get_settings.cache_clear()
    get_webhook_dispatcher.cache_clear()
    receiver = _Receiver([])
    dispatcher = get_webhook_dispatcher()
    dispatcher._client = httpx.AsyncClient(transport=httpx.MockTransport(receiver.handler))

    from app.main import app

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            async with app.router.lifespan_context(app):
                failing = await ac.post(
                    "/v1/agents",
                    json={
                        "name": "fail-bot",
                        "adapter": "echo",
                        "config": {"delay": 0, "fail_at_node": "tool"},
                    },
                )
                failed_run = await ac.post(
                    "/v1/runs", json={"agent_id": failing.json()["id"], "input": {"prompt": "x"}}
                )
                failed_id = failed_run.json()["id"]
                body = await _run_to(ac, failed_id, {"succeeded", "failed", "cancelled"})
                assert body["status"] == "failed", body

                slow = await ac.post(
                    "/v1/agents",
                    json={"name": "slow-bot", "adapter": "echo", "config": {"delay": 0.3}},
                )
                slow_run = await ac.post(
                    "/v1/runs", json={"agent_id": slow.json()["id"], "input": {"prompt": "y"}}
                )
                slow_id = slow_run.json()["id"]
                cancel = await ac.post(f"/v1/runs/{slow_id}/cancel")
                assert cancel.status_code == 204, cancel.text
                body = await _run_to(ac, slow_id, {"succeeded", "failed", "cancelled"})
                assert body["status"] == "cancelled", body
                await dispatcher.drain()
    finally:
        get_settings.cache_clear()
        get_webhook_dispatcher.cache_clear()
        os.environ.pop("AGENTFLOW_WEBHOOK_URLS", None)

    by_run = {json.loads(r.content)["run_id"]: r for r in receiver.requests}
    assert set(by_run) == {failed_id, slow_id}
    failed_payload = json.loads(by_run[failed_id].content)
    assert by_run[failed_id].headers[EVENT_HEADER] == "run.failed"
    assert failed_payload["type"] == "run.failed"
    assert failed_payload["data"]["error"]
    cancelled_payload = json.loads(by_run[slow_id].content)
    assert by_run[slow_id].headers[EVENT_HEADER] == "run.cancelled"
    assert cancelled_payload["data"] == {"error": "cancelled"}
