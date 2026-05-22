#!/usr/bin/env python3
"""End-to-end smoke test for the Java API + Python worker stack."""

from __future__ import annotations

import asyncio
import sys

import httpx

POLL_ATTEMPTS = 120
POLL_INTERVAL_SECONDS = 0.5
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


async def smoke_test(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        health = await client.get("/v1/health")
        health.raise_for_status()
        body = health.json()
        assert body["status"] == "ok", body
        assert "echo" in body["adapters"], body

        create_agent = await client.post(
            "/v1/agents",
            json={"name": "ci-smoke-echo", "adapter": "echo", "config": {"delay": 0}},
        )
        assert create_agent.status_code == 201, create_agent.text
        agent_id = create_agent.json()["id"]

        create_run = await client.post(
            "/v1/runs",
            json={"agent_id": agent_id, "input": {"prompt": "ci-smoke"}},
        )
        assert create_run.status_code == 202, create_run.text
        run_id = create_run.json()["id"]
        assert create_run.json()["status"] == "pending", create_run.text

        detail: dict[str, object] = {}
        for _ in range(POLL_ATTEMPTS):
            run_detail = await client.get(f"/v1/runs/{run_id}")
            run_detail.raise_for_status()
            detail = run_detail.json()
            if detail["status"] in TERMINAL_STATUSES:
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        assert detail["status"] == "succeeded", detail
        assert detail["output"] == {"reply": "echo: ci-smoke"}, detail
        assert len(detail["steps"]) == 3, detail
        assert {step["node"] for step in detail["steps"]} == {"plan", "tool", "reply"}


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    asyncio.run(smoke_test(base_url.rstrip("/")))
    print(f"java stack smoke passed ({base_url})")


if __name__ == "__main__":
    main()
