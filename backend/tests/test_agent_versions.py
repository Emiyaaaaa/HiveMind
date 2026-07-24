"""Agent version management tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_agent_starts_at_v1(client):
    resp = await client.post(
        "/v1/agents",
        json={"name": "ver-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["version"] == 1

    versions = await client.get(f"/v1/agents/{body['id']}/versions")
    assert versions.status_code == 200
    rows = versions.json()
    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert rows[0]["note"] == "initial"
    assert rows[0]["config"] == {"delay": 0}


@pytest.mark.asyncio
async def test_update_bumps_version_and_diff(client):
    created = await client.post(
        "/v1/agents",
        json={
            "name": "diff-bot",
            "adapter": "echo",
            "config": {"model": "a", "tools": ["echo"]},
        },
    )
    agent_id = created.json()["id"]

    updated = await client.patch(
        f"/v1/agents/{agent_id}",
        json={
            "adapter": "langgraph",
            "config": {"model": "b", "tools": ["echo"], "stream_tokens": True},
            "note": "switch to langgraph",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["adapter"] == "langgraph"

    v2 = await client.get(f"/v1/agents/{agent_id}/versions/2")
    assert v2.status_code == 200
    assert v2.json()["note"] == "switch to langgraph"

    diff = await client.get(
        f"/v1/agents/{agent_id}/versions/diff",
        params={"from": 1, "to": 2},
    )
    assert diff.status_code == 200
    body = diff.json()
    assert body["adapter"] == {"from": "echo", "to": "langgraph"}
    assert body["config"]["changed"]["model"] == {"from": "a", "to": "b"}
    assert body["config"]["added"]["stream_tokens"] is True


@pytest.mark.asyncio
async def test_name_only_update_does_not_bump_version(client):
    created = await client.post(
        "/v1/agents",
        json={"name": "rename-me", "adapter": "echo", "config": {}},
    )
    agent_id = created.json()["id"]

    updated = await client.patch(
        f"/v1/agents/{agent_id}",
        json={"name": "renamed"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "renamed"
    assert updated.json()["version"] == 1

    versions = await client.get(f"/v1/agents/{agent_id}/versions")
    assert len(versions.json()) == 1


@pytest.mark.asyncio
async def test_restore_creates_new_version(client):
    created = await client.post(
        "/v1/agents",
        json={"name": "restore-bot", "adapter": "echo", "config": {"x": 1}},
    )
    agent_id = created.json()["id"]

    await client.patch(
        f"/v1/agents/{agent_id}",
        json={"config": {"x": 2}, "adapter": "langgraph"},
    )

    restored = await client.post(f"/v1/agents/{agent_id}/versions/1/restore")
    assert restored.status_code == 200
    body = restored.json()
    assert body["version"] == 3
    assert body["adapter"] == "echo"
    assert body["config"] == {"x": 1}

    versions = await client.get(f"/v1/agents/{agent_id}/versions")
    notes = {row["version"]: row["note"] for row in versions.json()}
    assert notes[3] == "restored from v1"
