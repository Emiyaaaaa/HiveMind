"""Typed REST client for the AgentFlow API."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

import httpx

from agentflow_sdk.models import Run, RunCreateRequest


class AgentFlowClient:
    """Thin wrapper around the AgentFlow `/v1` HTTP API."""

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

    def create_run(
        self,
        agent_id: str,
        *,
        input: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        adapter: str | None = None,
    ) -> Run:
        """POST /v1/runs — enqueue a run and return the pending Run record."""
        payload: MutableMapping[str, Any] = {"agent_id": agent_id}
        if input is not None:
            payload["input"] = dict(input)
        if metadata is not None:
            payload["metadata"] = dict(metadata)
        if adapter is not None:
            payload["adapter"] = adapter
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

    def health(self) -> dict[str, Any]:
        response = self._client.get("/v1/health")
        response.raise_for_status()
        return response.json()
