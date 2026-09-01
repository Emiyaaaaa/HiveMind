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


@pytest.mark.asyncio
async def test_run_messages_preview_and_pagination(client):
    from sqlalchemy import delete

    from app.db.session import SessionLocal
    from app.models import Message

    create = await client.post(
        "/v1/agents",
        json={"name": "msg-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    agent_id = create.json()["id"]
    run_response = await client.post(
        "/v1/runs",
        json={"agent_id": agent_id, "input": {"prompt": "seed"}},
    )
    run_id = run_response.json()["id"]
    await _poll_until(client, run_id, {"succeeded"})

    async with SessionLocal() as session:
        await session.execute(delete(Message).where(Message.run_id == run_id))
        await session.commit()
        for index in range(60):
            session.add(
                Message(
                    run_id=run_id,
                    index=index,
                    role="user",
                    content=f"message-{index}",
                )
            )
        await session.commit()

    detail = await client.get(f"/v1/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["messages"]) == 50
    assert body["messages_truncated"] is True
    assert body["messages"][0]["index"] == 10
    assert body["messages"][-1]["index"] == 59

    latest = await client.get(f"/v1/runs/{run_id}/messages?limit=10")
    assert latest.status_code == 200, latest.text
    page = latest.json()
    assert len(page["items"]) == 10
    assert page["items"][0]["index"] == 50
    assert page["items"][-1]["index"] == 59
    assert page["has_more"] is True
    assert page["next_cursor"] == 50

    older = await client.get(f"/v1/runs/{run_id}/messages?cursor=50&limit=20")
    assert older.status_code == 200, older.text
    older_page = older.json()
    assert len(older_page["items"]) == 20
    assert older_page["items"][0]["index"] == 30
    assert older_page["items"][-1]["index"] == 49
    assert older_page["has_more"] is True

    oldest = await client.get(f"/v1/runs/{run_id}/messages?cursor=30&limit=50")
    assert oldest.status_code == 200, oldest.text
    oldest_page = oldest.json()
    assert len(oldest_page["items"]) == 30
    assert oldest_page["items"][0]["index"] == 0
    assert oldest_page["items"][-1]["index"] == 29
    assert oldest_page["has_more"] is False
    assert oldest_page["next_cursor"] is None
