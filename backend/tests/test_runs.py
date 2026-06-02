import asyncio

import pytest


@pytest.mark.asyncio
async def test_echo_run_end_to_end(client):
    create = await client.post(
        "/v1/agents",
        json={"name": "echo-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    assert create.status_code == 201, create.text
    agent_id = create.json()["id"]

    run_response = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "hi"}},
    )
    assert run_response.status_code == 202, run_response.text
    run_id = run_response.json()["id"]

    # Background adapter task may not be finished by the time the response
    # returns. Poll the run until it reaches a terminal state.
    for _ in range(50):
        detail = await client.get(f"/v1/runs/{run_id}")
        body = detail.json()
        if body["status"] in {"succeeded", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.05)

    assert body["status"] == "succeeded", body
    assert body["output"] == {"reply": "echo: hi"}
    assert len(body["steps"]) == 3
    assert {step["node"] for step in body["steps"]} == {"plan", "tool", "reply"}
    assert any(msg["role"] == "assistant" for msg in body["messages"])
    assert body["usage"]["tokens_in"] > 0
    assert body["usage"]["tokens_out"] > 0
    reply_step = next(s for s in body["steps"] if s["node"] == "reply")
    assert reply_step["tokens_in"] is not None
    assert reply_step["cost_usd"] is not None


async def _poll_until(client, run_id: str, statuses: set[str], *, attempts: int = 80):
    body: dict = {}
    for _ in range(attempts):
        detail = await client.get(f"/v1/runs/{run_id}")
        body = detail.json()
        if body["status"] in statuses:
            return body
        await asyncio.sleep(0.05)
    return body


@pytest.mark.asyncio
async def test_retry_failed_run_from_checkpoint(client):
    create = await client.post(
        "/v1/agents",
        json={
            "name": "retry-bot",
            "adapter": "echo",
            "config": {"delay": 0, "fail_at_node": "tool"},
        },
    )
    agent_id = create.json()["id"]

    run_response = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "retry-me"}},
    )
    run_id = run_response.json()["id"]

    body = await _poll_until(client, run_id, {"failed"})
    assert body["status"] == "failed"
    assert len(body["checkpoints"]) >= 1

    retry = await client.post(f"/v1/runs/{run_id}/retry")
    assert retry.status_code == 202, retry.text
    assert retry.json()["status"] == "pending"

    body = await _poll_until(client, run_id, {"succeeded", "failed"})
    assert body["status"] == "succeeded", body
    assert body["output"] == {"reply": "echo: retry-me"}


@pytest.mark.asyncio
async def test_resume_waiting_human(client):
    create = await client.post(
        "/v1/agents",
        json={
            "name": "resume-bot",
            "adapter": "echo",
            "config": {"delay": 0, "pause_before_reply": True},
        },
    )
    agent_id = create.json()["id"]

    run_response = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "hold"}},
    )
    run_id = run_response.json()["id"]

    body = await _poll_until(client, run_id, {"waiting_human"})
    assert body["status"] == "waiting_human"

    resume = await client.post(
        f"/v1/runs/{run_id}/resume",
        json={"input": {"approval": "ok"}},
    )
    assert resume.status_code == 202, resume.text

    body = await _poll_until(client, run_id, {"succeeded", "failed"})
    assert body["status"] == "succeeded", body
    assert "ok" in body["output"]["reply"]


@pytest.mark.asyncio
async def test_retry_conflict_when_not_failed(client):
    create = await client.post(
        "/v1/agents",
        json={"name": "ok-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = create.json()["id"]
    run_response = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "x"}},
    )
    run_id = run_response.json()["id"]
    await _poll_until(client, run_id, {"succeeded"})

    retry = await client.post(f"/v1/runs/{run_id}/retry")
    assert retry.status_code == 409
