"""Typed REST client for the Hivemind API.

Covers the run lifecycle end to end: create, poll/wait, cancel, retry a
failed run, resume a ``waiting_human`` run after approval, page through the
transcript, read the cancel/resume audit trail, and drive multi-run
conversations through threads. Live streaming lives in ``events.py``.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any

import httpx

from agentflow_sdk.models import MessagePage, Run, RunAuditEvent, Thread

TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})


class RunTimeoutError(TimeoutError):
    """``wait_for_run`` gave up before the run reached a wanted status."""

    def __init__(self, run: Run, timeout: float) -> None:
        super().__init__(f"run {run.id} still {run.status} after {timeout:.1f}s")
        self.run = run


def _page_params(cursor: int | str | None, limit: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if cursor is not None:
        params["cursor"] = cursor
    if limit is not None:
        params["limit"] = limit
    return params


class AgentFlowClient:
    """Thin wrapper around the Hivemind `/v1` HTTP API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if api_key:
            headers["X-Api-Key"] = api_key
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> AgentFlowClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- runs ---------------------------------------------------------------

    def create_run(
        self,
        agent_id: str,
        *,
        input: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        adapter: str | None = None,
        thread_id: str | None = None,
    ) -> Run:
        """POST /v1/runs — enqueue a run and return the pending Run record.

        Pass ``thread_id`` to continue a conversation: the worker seeds the
        adapter with the thread's recent turns, so the client does not need
        to replay history into ``input``.
        """
        payload: MutableMapping[str, Any] = {"agent_id": agent_id}
        if input is not None:
            payload["input"] = dict(input)
        if metadata is not None:
            payload["metadata"] = dict(metadata)
        if adapter is not None:
            payload["adapter"] = adapter
        if thread_id is not None:
            payload["thread_id"] = thread_id
        response = self._client.post("/v1/runs", json=payload)
        response.raise_for_status()
        return Run.from_dict(response.json())

    def get_run(self, run_id: str) -> Run:
        response = self._client.get(f"/v1/runs/{run_id}")
        response.raise_for_status()
        return Run.from_dict(response.json())

    def cancel_run(self, run_id: str) -> None:
        response = self._client.post(f"/v1/runs/{run_id}/cancel")
        response.raise_for_status()

    def retry_run(self, run_id: str, *, checkpoint_index: int | None = None) -> Run:
        """POST /v1/runs/{id}/retry — re-queue a **failed** run.

        Uses the latest checkpoint unless ``checkpoint_index`` picks an older
        one. The server answers 409 when the run is not ``failed``.
        """
        body: dict[str, Any] = {}
        if checkpoint_index is not None:
            body["checkpoint_index"] = checkpoint_index
        response = self._client.post(f"/v1/runs/{run_id}/retry", json=body)
        response.raise_for_status()
        return Run.from_dict(response.json())

    def resume_run(self, run_id: str, *, input: Mapping[str, Any] | None = None) -> Run:
        """POST /v1/runs/{id}/resume — continue a ``waiting_human`` run.

        ``input`` (for example ``{"approval": "approved"}``) is merged into the
        run's persisted input and handed to the adapter. 409 when the run is
        not waiting for a human.
        """
        body: dict[str, Any] = {}
        if input is not None:
            body["input"] = dict(input)
        response = self._client.post(f"/v1/runs/{run_id}/resume", json=body)
        response.raise_for_status()
        return Run.from_dict(response.json())

    def wait_for_run(
        self,
        run_id: str,
        *,
        timeout: float = 300.0,
        poll_interval: float = 0.5,
        until: frozenset[str] | set[str] = TERMINAL_STATUSES | {"waiting_human"},
    ) -> Run:
        """Poll ``GET /v1/runs/{id}`` until the status is in ``until``.

        Stops on ``waiting_human`` by default so an approval script can
        inspect the run, call ``resume_run`` and wait again. Use
        ``subscribe_run_events`` instead when you need step-level progress.
        Raises ``RunTimeoutError`` (carrying the last ``Run``) on timeout.
        """
        deadline = time.monotonic() + timeout
        while True:
            run = self.get_run(run_id)
            if run.status in until:
                return run
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RunTimeoutError(run, timeout)
            # Never sleep past the deadline: timeout=0.1 with poll_interval=10
            # must fail after ~0.1s, not 10s.
            time.sleep(min(poll_interval, remaining))

    def list_run_messages(
        self, run_id: str, *, cursor: int | None = None, limit: int | None = None
    ) -> MessagePage:
        """GET /v1/runs/{id}/messages — newest page first; follow ``next_cursor``."""
        response = self._client.get(
            f"/v1/runs/{run_id}/messages", params=_page_params(cursor, limit)
        )
        response.raise_for_status()
        return MessagePage.from_dict(response.json())

    def iter_run_messages(
        self, run_id: str, *, page_size: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield every message of a run, newest page first, following cursors."""
        cursor: int | None = None
        while True:
            page = self.list_run_messages(run_id, cursor=cursor, limit=page_size)
            yield from page.items
            if not page.has_more or page.next_cursor is None:
                return
            cursor = int(page.next_cursor)

    def get_run_audit(self, run_id: str) -> list[RunAuditEvent]:
        """GET /v1/runs/{id}/audit — cancel/resume records, oldest first."""
        response = self._client.get(f"/v1/runs/{run_id}/audit")
        response.raise_for_status()
        return [RunAuditEvent.from_dict(item) for item in response.json()]

    # -- threads ------------------------------------------------------------

    def create_thread(
        self,
        agent_id: str,
        *,
        title: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> Thread:
        """POST /v1/threads — open a conversation for ``create_run(thread_id=...)``."""
        payload: dict[str, Any] = {"agent_id": agent_id}
        if title is not None:
            payload["title"] = title
        if user_id is not None:
            payload["user_id"] = user_id
        if project_id is not None:
            payload["project_id"] = project_id
        response = self._client.post("/v1/threads", json=payload)
        response.raise_for_status()
        return Thread.from_dict(response.json())

    def list_threads(self, *, limit: int | None = None) -> list[Thread]:
        """GET /v1/threads — threads visible to the caller, newest first."""
        response = self._client.get("/v1/threads", params=_page_params(None, limit))
        response.raise_for_status()
        return [Thread.from_dict(item) for item in response.json()]

    def get_thread(self, thread_id: str) -> Thread:
        response = self._client.get(f"/v1/threads/{thread_id}")
        response.raise_for_status()
        return Thread.from_dict(response.json())

    def list_thread_runs(self, thread_id: str, *, limit: int | None = None) -> list[Run]:
        """GET /v1/threads/{id}/runs — runs in the thread, oldest first."""
        response = self._client.get(
            f"/v1/threads/{thread_id}/runs", params=_page_params(None, limit)
        )
        response.raise_for_status()
        return [Run.from_dict(item) for item in response.json()]

    def list_thread_messages(
        self, thread_id: str, *, cursor: str | None = None, limit: int | None = None
    ) -> MessagePage:
        """GET /v1/threads/{id}/messages — cross-run transcript, newest page first.

        Items carry ``run_id`` in addition to the Message fields; the cursor is
        an opaque string.
        """
        response = self._client.get(
            f"/v1/threads/{thread_id}/messages", params=_page_params(cursor, limit)
        )
        response.raise_for_status()
        return MessagePage.from_dict(response.json())

    # -- misc ---------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        response = self._client.get("/v1/health")
        response.raise_for_status()
        return response.json()
