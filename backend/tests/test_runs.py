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
