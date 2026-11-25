#!/usr/bin/env python3
"""End-to-end checks for the Java API + Python worker stack.

The same coroutine runs against a live base URL (this script) and against the
in-process API (backend/tests/test_stack_smoke.py). Checks stay on the public
HTTP contract the echo adapter can satisfy without extra services.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

import httpx

POLL_ATTEMPTS = 120
POLL_INTERVAL_SECONDS = 0.25
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def expect(condition: object, detail: object) -> None:
    if not condition:
        raise AssertionError(detail)


def _name(prefix: str) -> str:
    return f"{prefix}-{time.time_ns()}"


async def poll_until(
    client: httpx.AsyncClient,
    run_id: str,
    statuses: set[str],
) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for _ in range(POLL_ATTEMPTS):
        response = await client.get(f"/v1/runs/{run_id}")
        response.raise_for_status()
        last = response.json()
        if last.get("status") in statuses:
            return last
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"run {run_id} stuck at {last.get('status')}: {last}")


async def create_agent(
    client: httpx.AsyncClient,
    name: str,
    config: dict[str, Any],
) -> str:
    response = await client.post(
        "/v1/agents",
        json={"name": name, "adapter": "echo", "config": config},
    )
    expect(response.status_code == 201, response.text)
    body = response.json()
    expect(body["adapter"] == "echo", body)
    expect(body["version"] == 1, body)
    return str(body["id"])


async def create_run(
    client: httpx.AsyncClient,
    agent_id: str,
    prompt: str,
    *,
    thread_id: str | None = None,
) -> str:
    payload: dict[str, Any] = {"agent_id": agent_id, "input": {"prompt": prompt}}
    if thread_id is not None:
        payload["thread_id"] = thread_id
    response = await client.post("/v1/runs", json=payload)
    expect(response.status_code == 202, response.text)
    body = response.json()
    expect(body["status"] == "pending", body)
    return str(body["id"])


async def check_health(client: httpx.AsyncClient) -> None:
    health = await client.get("/v1/health")
    health.raise_for_status()
    body = health.json()
    expect(body["status"] == "ok", body)
    expect("echo" in body["adapters"], body)


async def check_echo_run(client: httpx.AsyncClient, agent_id: str) -> str:
    run_id = await create_run(client, agent_id, "ci-smoke")
    detail = await poll_until(client, run_id, TERMINAL_STATUSES)
    expect(detail["status"] == "succeeded", detail)
    expect(detail["output"] == {"reply": "echo: ci-smoke"}, detail)
    expect(len(detail["steps"]) == 3, detail)
    expect({step["node"] for step in detail["steps"]} == {"plan", "tool", "reply"}, detail)
    expect(any(msg["role"] == "assistant" for msg in detail["messages"]), detail)
    expect(detail["usage"]["tokens_in"] > 0, detail)
    expect(detail["usage"]["tokens_out"] > 0, detail)
    reply = next(step for step in detail["steps"] if step["node"] == "reply")
    expect(reply["tokens_in"] is not None, reply)
    expect(reply["cost_usd"] is not None, reply)

    listed = await client.get("/v1/runs", params={"limit": 50})
    listed.raise_for_status()
    expect(any(row["id"] == run_id for row in listed.json()), listed.text)
    return run_id


async def check_message_page(client: httpx.AsyncClient, run_id: str) -> None:
    latest = await client.get(f"/v1/runs/{run_id}/messages", params={"limit": 1})
    latest.raise_for_status()
    page = latest.json()
    expect(len(page["items"]) == 1, page)
    expect(page["has_more"] is True, page)
    expect(page["next_cursor"] == page["items"][0]["index"], page)
    expect(page["items"][0]["role"] == "assistant", page)

    older = await client.get(
        f"/v1/runs/{run_id}/messages",
        params={"cursor": page["next_cursor"], "limit": 10},
    )
    older.raise_for_status()
    older_page = older.json()
    expect(len(older_page["items"]) == 1, older_page)
    expect(older_page["items"][0]["role"] == "user", older_page)
    expect(older_page["items"][0]["content"] == "ci-smoke", older_page)
    expect(older_page["has_more"] is False, older_page)
    expect(older_page["next_cursor"] is None, older_page)


async def check_retry(client: httpx.AsyncClient, succeeded_run_id: str) -> None:
    conflict = await client.post(f"/v1/runs/{succeeded_run_id}/retry")
    expect(conflict.status_code == 409, conflict.text)
    expect("detail" in conflict.json(), conflict.text)

    agent_id = await create_agent(
        client,
        _name("ci-retry"),
        {"delay": 0, "fail_at_node": "tool"},
    )
    run_id = await create_run(client, agent_id, "retry-me")
    failed = await poll_until(client, run_id, TERMINAL_STATUSES)
    expect(failed["status"] == "failed", failed)
    expect("simulated tool failure" in str(failed.get("error")), failed)
    expect(len(failed["checkpoints"]) >= 1, failed)

    retry = await client.post(f"/v1/runs/{run_id}/retry")
    expect(retry.status_code == 202, retry.text)
    expect(retry.json()["status"] == "pending", retry.text)

    recovered = await poll_until(client, run_id, TERMINAL_STATUSES)
    expect(recovered["status"] == "succeeded", recovered)
    expect(recovered["output"] == {"reply": "echo: retry-me"}, recovered)


async def check_resume(client: httpx.AsyncClient) -> None:
    agent_id = await create_agent(
        client,
        _name("ci-resume"),
        {"delay": 0, "pause_before_reply": True},
    )
    run_id = await create_run(client, agent_id, "hold")
    paused = await poll_until(client, run_id, {"waiting_human", *TERMINAL_STATUSES})
    expect(paused["status"] == "waiting_human", paused)

    blocked = await client.post(f"/v1/runs/{run_id}/retry")
    expect(blocked.status_code == 409, blocked.text)

    resume = await client.post(
        f"/v1/runs/{run_id}/resume",
        json={"input": {"approval": "ok"}},
    )
    expect(resume.status_code == 202, resume.text)

    done = await poll_until(client, run_id, TERMINAL_STATUSES)
    expect(done["status"] == "succeeded", done)
    expect("ok" in done["output"]["reply"], done)

    audit = await client.get(f"/v1/runs/{run_id}/audit")
    audit.raise_for_status()
    actions = [event["action"] for event in audit.json()]
    expect("resume" in actions, audit.text)


async def check_cancel(client: httpx.AsyncClient) -> None:
    agent_id = await create_agent(client, _name("ci-cancel"), {"delay": 1.0})
    run_id = await create_run(client, agent_id, "slow")
    cancel = await client.post(f"/v1/runs/{run_id}/cancel")
    expect(cancel.status_code == 204, cancel.text)

    detail = await poll_until(client, run_id, TERMINAL_STATUSES)
    expect(detail["status"] == "cancelled", detail)

    again = await client.post(f"/v1/runs/{run_id}/cancel")
    expect(again.status_code == 204, again.text)
    audit = await client.get(f"/v1/runs/{run_id}/audit")
    audit.raise_for_status()
    events = audit.json()
    expect(events, audit.text)
    expect(all(event["action"] == "cancel" for event in events), events)
    expect(all(event["run_id"] == run_id for event in events), events)


async def check_thread(client: httpx.AsyncClient) -> None:
    agent_id = await create_agent(client, _name("ci-thread"), {"delay": 0})
    created = await client.post(
        "/v1/threads",
        json={"agent_id": agent_id, "title": "ci-chat"},
    )
    expect(created.status_code == 201, created.text)
    thread = created.json()
    thread_id = str(thread["id"])
    expect(thread["agent_id"] == agent_id, thread)
    expect(thread["title"] == "ci-chat", thread)

    fetched = await client.get(f"/v1/threads/{thread_id}")
    fetched.raise_for_status()
    expect(fetched.json()["id"] == thread_id, fetched.text)

    first = await create_run(client, agent_id, "hello", thread_id=thread_id)
    first_body = await poll_until(client, first, TERMINAL_STATUSES)
    expect(first_body["status"] == "succeeded", first_body)
    expect(first_body["thread_id"] == thread_id, first_body)

    second = await create_run(client, agent_id, "follow-up", thread_id=thread_id)
    second_body = await poll_until(client, second, TERMINAL_STATUSES)
    expect(second_body["status"] == "succeeded", second_body)
    expect(second_body["output"] == {"reply": "echo: follow-up"}, second_body)

    solo = await create_run(client, agent_id, "solo")
    solo_body = await poll_until(client, solo, TERMINAL_STATUSES)
    expect(solo_body["status"] == "succeeded", solo_body)
    expect(solo_body.get("thread_id") is None, solo_body)

    messages = await client.get(f"/v1/threads/{thread_id}/messages")
    messages.raise_for_status()
    items = messages.json()["items"]
    contents = [item["content"] for item in items]
    expect("hello" in contents and "follow-up" in contents, items)
    expect(all(item["run_id"] in {first, second} for item in items), items)

    runs = await client.get(f"/v1/threads/{thread_id}/runs")
    runs.raise_for_status()
    run_ids = {row["id"] for row in runs.json()}
    expect(run_ids == {first, second}, runs.text)

    missing = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent_id,
            "thread_id": MISSING_ID,
            "input": {"prompt": "x"},
        },
    )
    expect(missing.status_code == 404, missing.text)


async def check_versions(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/agents",
        json={"name": _name("ci-version"), "adapter": "echo", "config": {"delay": 0}},
    )
    expect(response.status_code == 201, response.text)
    agent_id = response.json()["id"]

    renamed = await client.patch(f"/v1/agents/{agent_id}", json={"name": _name("ci-renamed")})
    expect(renamed.status_code == 200, renamed.text)
    expect(renamed.json()["version"] == 1, renamed.text)

    updated = await client.patch(
        f"/v1/agents/{agent_id}",
        json={"config": {"delay": 0, "tag": "v2"}, "note": "tune echo"},
    )
    expect(updated.status_code == 200, updated.text)
    expect(updated.json()["version"] == 2, updated.text)
    expect(updated.json()["config"]["tag"] == "v2", updated.text)

    version = await client.get(f"/v1/agents/{agent_id}/versions/2")
    version.raise_for_status()
    expect(version.json()["note"] == "tune echo", version.text)
    expect(version.json()["config"] == {"delay": 0, "tag": "v2"}, version.text)

    diff = await client.get(
        f"/v1/agents/{agent_id}/versions/diff",
        params={"from": 1, "to": 2},
    )
    diff.raise_for_status()
    body = diff.json()
    expect(body["from_version"] == 1 and body["to_version"] == 2, body)
    expect(body["config"]["added"]["tag"] == "v2", body)
    expect(body["config"]["changed"] == {}, body)

    restored = await client.post(f"/v1/agents/{agent_id}/versions/1/restore")
    expect(restored.status_code == 200, restored.text)
    expect(restored.json()["version"] == 3, restored.text)
    expect(restored.json()["config"] == {"delay": 0}, restored.text)
    expect(restored.json()["adapter"] == "echo", restored.text)

    versions = await client.get(f"/v1/agents/{agent_id}/versions")
    versions.raise_for_status()
    notes = {row["version"]: row["note"] for row in versions.json()}
    expect(notes[1] == "initial", notes)
    expect(notes[2] == "tune echo", notes)
    expect(notes[3] == "restored from v1", notes)

    missing = await client.get(f"/v1/agents/{agent_id}/versions/9")
    expect(missing.status_code == 404, missing.text)


async def check_batch(client: httpx.AsyncClient) -> None:
    agent_id = await create_agent(client, _name("ci-batch"), {"delay": 0})
    created = await client.post(
        "/v1/batches",
        json={
            "agent_id": agent_id,
            "items": [
                {"input": {"prompt": "one"}},
                {"input": {"prompt": "two"}},
            ],
        },
    )
    expect(created.status_code == 202, created.text)
    batch = created.json()
    expect(batch["total"] == 2, batch)
    expect(len(batch["run_ids"]) == 2, batch)
    expect(batch["agent_id"] == agent_id, batch)

    replies: dict[str, str] = {}
    for run_id in batch["run_ids"]:
        detail = await poll_until(client, run_id, TERMINAL_STATUSES)
        expect(detail["status"] == "succeeded", detail)
        replies[run_id] = detail["output"]["reply"]
    expect(set(replies.values()) == {"echo: one", "echo: two"}, replies)

    detail = await client.get(f"/v1/batches/{batch['id']}")
    detail.raise_for_status()
    progress = detail.json()
    expect(progress["status"] == "completed", progress)
    expect(progress["completed"] == 2, progress)
    expect(progress["run_ids"] == batch["run_ids"], progress)

    runs = await client.get(f"/v1/batches/{batch['id']}/runs")
    runs.raise_for_status()
    expect({row["id"] for row in runs.json()} == set(batch["run_ids"]), runs.text)

    empty = await client.post(
        "/v1/batches",
        json={"agent_id": agent_id, "items": []},
    )
    expect(empty.status_code in {400, 422}, empty.text)

    missing = await client.get(f"/v1/batches/{MISSING_ID}")
    expect(missing.status_code == 404, missing.text)


async def check_not_found(client: httpx.AsyncClient) -> None:
    unknown_agent = await client.post(
        "/v1/runs",
        json={"agent_id": MISSING_ID, "input": {"prompt": "nope"}},
    )
    expect(unknown_agent.status_code == 404, unknown_agent.text)
    expect("detail" in unknown_agent.json(), unknown_agent.text)

    unknown_run = await client.get(f"/v1/runs/{MISSING_ID}")
    expect(unknown_run.status_code == 404, unknown_run.text)

    unknown_thread = await client.get(f"/v1/threads/{MISSING_ID}")
    expect(unknown_thread.status_code == 404, unknown_thread.text)


async def run_checks(client: httpx.AsyncClient) -> None:
    await check_health(client)
    agent_id = await create_agent(client, _name("ci-smoke"), {"delay": 0})
    run_id = await check_echo_run(client, agent_id)
    await check_message_page(client, run_id)
    await check_retry(client, run_id)
    await check_resume(client)
    await check_cancel(client)
    await check_thread(client)
    await check_versions(client)
    await check_batch(client)
    await check_not_found(client)


async def smoke_test(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        await run_checks(client)


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    asyncio.run(smoke_test(base_url.rstrip("/")))
    print(f"java stack smoke passed ({base_url})")


if __name__ == "__main__":
    main()
