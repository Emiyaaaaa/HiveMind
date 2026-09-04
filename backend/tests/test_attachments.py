"""Multimodal attachment upload, bind, stream, and erase."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters import register_adapter
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.models.run import RunStatus
from app.runtime.object_store import LocalObjectStore, set_object_store
from ulid import ULID


@pytest.fixture
def attachment_store(tmp_path: Path):
    store = LocalObjectStore(tmp_path / "attachments")
    set_object_store(store)
    yield store
    set_object_store(None)


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
async def test_upload_download_and_bind_attachment(client, attachment_store):
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    upload = await client.post(
        "/v1/attachments",
        files={"file": ("pixel.png", BytesIO(png), "image/png")},
        data={"caption": "tiny"},
    )
    assert upload.status_code == 201, upload.text
    meta = upload.json()
    assert meta["filename"] == "pixel.png"
    assert meta["media_type"] == "image/png"
    assert meta["size_bytes"] == len(png)
    assert meta["caption"] == "tiny"
    assert meta["url"] == f"/v1/attachments/{meta['id']}"

    content = await client.get(f"/v1/attachments/{meta['id']}/content")
    assert content.status_code == 200
    assert content.content == png
    assert content.headers["content-type"].startswith("image/png")

    agent = await client.post(
        "/v1/agents",
        json={"name": "attach-bot", "adapter": "echo", "config": {"delay": 0}},
    )
    assert agent.status_code == 201, agent.text
    run = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent.json()["id"],
            "input": {
                "prompt": "describe",
                "attachments": [{"id": meta["id"]}],
            },
        },
    )
    assert run.status_code == 202, run.text
    body = await _poll_until(client, run.json()["id"], {"succeeded", "failed"})
    assert body["status"] == "succeeded"

    refreshed = await client.get(f"/v1/attachments/{meta['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["run_id"] == body["id"]


@pytest.mark.asyncio
async def test_langgraph_streams_and_persists_attachments(client, attachment_store):
    adapter_name = f"attach-capture-{ULID()}"
    captured: list[AdapterContext] = []

    class CaptureAdapter(OrchestratorAdapter):
        name = adapter_name

        async def run(self, ctx: AdapterContext) -> AdapterResult:
            captured.append(ctx)
            from app.runtime.attachments import emit_input_attachments

            await ctx.emit_step_started(index=0, node="vision")
            if ctx.attachments:
                await emit_input_attachments(ctx, list(ctx.attachments), step_index=0)
            prompt = str(ctx.input.get("prompt") or "")
            await ctx.emit_message(role="user", content=prompt, step_index=0)
            await ctx.emit_message(role="assistant", content=f"saw:{prompt}", step_index=0)
            await ctx.emit_step_completed(
                index=0, node="vision", output={"reply": f"saw:{prompt}"}
            )
            return AdapterResult(
                status=RunStatus.SUCCEEDED, output={"reply": f"saw:{prompt}"}
            )

    register_adapter(adapter_name, CaptureAdapter())

    png = b"fakepng-bytes"
    upload = await client.post(
        "/v1/attachments",
        files={"file": ("chart.png", BytesIO(png), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    attachment_id = upload.json()["id"]

    agent = await client.post(
        "/v1/agents",
        json={"name": "vision-bot", "adapter": adapter_name, "config": {}},
    )
    assert agent.status_code == 201, agent.text
    run = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent.json()["id"],
            "input": {
                "prompt": "what is this?",
                "attachments": [attachment_id],
            },
        },
    )
    assert run.status_code == 202, run.text
    body = await _poll_until(client, run.json()["id"], {"succeeded", "failed"})
    assert body["status"] == "succeeded"
    assert len(captured) == 1
    assert len(captured[0].attachments) == 1
    assert captured[0].attachments[0].id == attachment_id

    messages = body["messages"]
    attachment_msgs = [
        m for m in messages if (m.get("extra") or {}).get("kind") == "attachment"
    ]
    assert len(attachment_msgs) == 1
    refs = attachment_msgs[0]["extra"]["attachments"]
    assert refs[0]["id"] == attachment_id
    assert refs[0]["filename"] == "chart.png"


@pytest.mark.asyncio
async def test_erase_run_deletes_attachment_blob(client, attachment_store, tmp_path):
    png = b"erase-me"
    upload = await client.post(
        "/v1/attachments",
        files={"file": ("gone.png", BytesIO(png), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    attachment_id = upload.json()["id"]
    storage_key = None
    # Resolve storage path after bind.
    agent = await client.post(
        "/v1/agents",
        json={"name": "erase-attach", "adapter": "echo", "config": {"delay": 0}},
    )
    run = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent.json()["id"],
            "input": {"prompt": "x", "attachments": [attachment_id]},
        },
    )
    body = await _poll_until(client, run.json()["id"], {"succeeded", "failed"})
    assert body["status"] == "succeeded"

    meta = await client.get(f"/v1/attachments/{attachment_id}")
    assert meta.status_code == 200

    erase = await client.post(f"/v1/runs/{body['id']}/erase")
    assert erase.status_code == 200, erase.text

    missing = await client.get(f"/v1/attachments/{attachment_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_missing_attachment_ref_returns_404(client, attachment_store):
    agent = await client.post(
        "/v1/agents",
        json={"name": "missing-attach", "adapter": "echo", "config": {"delay": 0}},
    )
    assert agent.status_code == 201
    run = await client.post(
        "/v1/runs",
        json={
            "agent_id": agent.json()["id"],
            "input": {
                "prompt": "x",
                "attachments": [{"id": "01MISSINGATTACHMENTID0000"}],
            },
        },
    )
    assert run.status_code == 404
