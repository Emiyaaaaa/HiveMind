"""AgentFlowClient against a scripted httpx transport (no server needed)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from agentflow_sdk import (
    AgentFlowClient,
    MessagePage,
    Run,
    RunAuditEvent,
    RunTimeoutError,
    Thread,
)

BASE = "http://api.test"


def _run(run_id: str = "01RUN", status: str = "pending", **extra: Any) -> dict[str, Any]:
    return {
        "id": run_id,
        "tenant_id": "default",
        "agent_id": "01AGENT",
        "adapter": "echo",
        "status": status,
        "input": {"prompt": "hi"},
        "created_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
        **extra,
    }


class _Server:
    """Route table keyed by ``METHOD path``; records every request."""

    def __init__(self) -> None:
        self.routes: dict[str, list[tuple[int, Any]]] = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, *responses: tuple[int, Any]) -> None:
        self.routes[f"{method} {path}"] = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path}"
        queue = self.routes.get(key)
        if not queue:
            return httpx.Response(404, json={"detail": f"no route {key}"})
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(status, json=body)


@pytest.fixture
def server() -> _Server:
    return _Server()


@pytest.fixture
def client(server: _Server) -> AgentFlowClient:
    http = httpx.Client(
        base_url=BASE,
        transport=httpx.MockTransport(server.handler),
        headers={"X-Api-Key": "k"},
    )
    return AgentFlowClient(BASE, client=http)


def _body(request: httpx.Request) -> Any:
    return json.loads(request.content) if request.content else None


def test_create_run_forwards_thread_id(server: _Server, client: AgentFlowClient):
    server.on("POST", "/v1/runs", (202, _run(thread_id="01THREAD")))
    run = client.create_run("01AGENT", input={"prompt": "hi"}, thread_id="01THREAD")
    assert isinstance(run, Run)
    assert _body(server.requests[0]) == {
        "agent_id": "01AGENT",
        "input": {"prompt": "hi"},
        "thread_id": "01THREAD",
    }


def test_retry_and_resume_post_optional_bodies(server: _Server, client: AgentFlowClient):
    server.on("POST", "/v1/runs/01RUN/retry", (202, _run()))
    server.on("POST", "/v1/runs/01RUN/resume", (202, _run()))

    assert client.retry_run("01RUN").status == "pending"
    assert client.retry_run("01RUN", checkpoint_index=2).status == "pending"
    assert client.resume_run("01RUN", input={"approval": "approved"}).status == "pending"

    assert _body(server.requests[0]) == {}
    assert _body(server.requests[1]) == {"checkpoint_index": 2}
    assert _body(server.requests[2]) == {"input": {"approval": "approved"}}


def test_retry_conflict_raises_http_status_error(server: _Server, client: AgentFlowClient):
    server.on("POST", "/v1/runs/01RUN/retry", (409, {"detail": "run is not failed"}))
    with pytest.raises(httpx.HTTPStatusError) as exc:
        client.retry_run("01RUN")
    assert exc.value.response.status_code == 409


def test_wait_for_run_stops_on_waiting_human_then_terminal(
    server: _Server, client: AgentFlowClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("agentflow_sdk.client.time.sleep", lambda _s: None)
    server.on(
        "GET",
        "/v1/runs/01RUN",
        (200, _run(status="running")),
        (200, _run(status="waiting_human")),
        (200, _run(status="succeeded", output={"reply": "ok"})),
    )

    paused = client.wait_for_run("01RUN", poll_interval=0)
    assert paused.status == "waiting_human"
    done = client.wait_for_run("01RUN", poll_interval=0)
    assert done.status == "succeeded"
    assert done.output == {"reply": "ok"}
    assert len(server.requests) == 3


def test_wait_for_run_times_out_with_last_run(
    server: _Server, client: AgentFlowClient, monkeypatch: pytest.MonkeyPatch
):
    ticks = iter([0.0, 0.0, 10.0, 10.0])
    monkeypatch.setattr("agentflow_sdk.client.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("agentflow_sdk.client.time.sleep", lambda _s: None)
    server.on("GET", "/v1/runs/01RUN", (200, _run(status="running")))

    with pytest.raises(RunTimeoutError) as exc:
        client.wait_for_run("01RUN", timeout=5)
    assert exc.value.run.status == "running"
    assert "01RUN" in str(exc.value)


def test_message_pagination_follows_cursor(server: _Server, client: AgentFlowClient):
    pages = [
        (200, {"items": [{"index": 2}, {"index": 3}], "next_cursor": 2, "has_more": True}),
        (200, {"items": [{"index": 0}, {"index": 1}], "next_cursor": None, "has_more": False}),
    ]
    server.on("GET", "/v1/runs/01RUN/messages", *pages)

    first = client.list_run_messages("01RUN", limit=2)
    assert isinstance(first, MessagePage)
    assert first.next_cursor == 2 and first.has_more
    assert dict(server.requests[0].url.params) == {"limit": "2"}

    server.on("GET", "/v1/runs/01RUN/messages", *pages)  # fresh script for the iterator
    indexes = [m["index"] for m in client.iter_run_messages("01RUN", page_size=2)]
    assert indexes == [2, 3, 0, 1]
    # Second call of the iterator passed the cursor from page one.
    assert dict(server.requests[2].url.params) == {"cursor": "2", "limit": "2"}


def test_audit_events_are_typed(server: _Server, client: AgentFlowClient):
    server.on(
        "GET",
        "/v1/runs/01RUN/audit",
        (
            200,
            [
                {
                    "id": "01A",
                    "tenant_id": "default",
                    "run_id": "01RUN",
                    "action": "resume",
                    "actor_subject": "ops",
                    "actor_role": "operator",
                    "detail": {"checkpoint_index": 1},
                    "created_at": "2026-09-15T00:00:00Z",
                }
            ],
        ),
    )
    events = client.get_run_audit("01RUN")
    assert events == [
        RunAuditEvent(
            id="01A",
            run_id="01RUN",
            action="resume",
            actor_subject="ops",
            actor_role="operator",
            created_at="2026-09-15T00:00:00Z",
            detail={"checkpoint_index": 1},
        )
    ]


def test_threads_round_trip(server: _Server, client: AgentFlowClient):
    thread = {
        "id": "01THREAD",
        "tenant_id": "default",
        "project_id": None,
        "agent_id": "01AGENT",
        "user_id": "u1",
        "title": "Support",
        "created_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
    }
    server.on("POST", "/v1/threads", (201, thread))
    server.on("GET", "/v1/threads/01THREAD", (200, thread))
    server.on("GET", "/v1/threads/01THREAD/runs", (200, [_run("01R1"), _run("01R2")]))
    server.on(
        "GET",
        "/v1/threads/01THREAD/messages",
        (
            200,
            {"items": [{"run_id": "01R2", "index": 0}], "next_cursor": "k|0|x", "has_more": True},
        ),
    )

    created = client.create_thread("01AGENT", title="Support", user_id="u1")
    assert isinstance(created, Thread) and created.title == "Support"
    assert _body(server.requests[0]) == {"agent_id": "01AGENT", "title": "Support", "user_id": "u1"}
    assert client.get_thread("01THREAD").id == "01THREAD"
    assert [r.id for r in client.list_thread_runs("01THREAD", limit=10)] == ["01R1", "01R2"]
    assert dict(server.requests[2].url.params) == {"limit": "10"}
    page = client.list_thread_messages("01THREAD", cursor="k|1|y", limit=1)
    assert page.next_cursor == "k|0|x" and page.items[0]["run_id"] == "01R2"
    assert dict(server.requests[3].url.params) == {"cursor": "k|1|y", "limit": "1"}
