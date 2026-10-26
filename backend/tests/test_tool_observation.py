"""Deterministic tool-result previews for bounded Agent observations."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.adapters.base import AdapterContext
from app.adapters.langgraph_adapter import LangGraphAdapter
from app.adapters.tool_registry import register_tool
from app.models.run import RunStatus
from app.runtime.tokens import estimate_tokens
from app.runtime.tool_observation import (
    MIN_OBSERVATION_TOKENS,
    parse_tool_observation_config,
    serialize_tool_observation,
)


class _RecordingContext(AdapterContext):
    def __init__(self, **kwargs: Any) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        super().__init__(
            run_id="01TEST",
            agent_id="01AGENT",
            agent_config={},
            input={"prompt": "hello"},
            emit=self._emit,
            **kwargs,
        )

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def test_small_result_keeps_legacy_json_shape() -> None:
    result = {"status": "ok", "items": [1, 2]}

    observed = serialize_tool_observation(result, max_tokens=100)

    assert json.loads(observed) == result


def test_large_mapping_keeps_priority_fields_and_valid_json() -> None:
    result = {
        "payload": "x" * 600,
        "message": "request completed",
        "status": "ok",
        "id": "run-123",
        "items": list(range(100)),
    }

    observed = serialize_tool_observation(result, max_tokens=80)
    decoded = json.loads(observed)

    assert estimate_tokens(observed) <= 80
    assert decoded["_observation"]["truncated"] is True
    assert decoded["_observation"]["original_tokens"] > 80
    assert decoded["status"] == "ok"
    assert decoded["id"] == "run-123"


def test_large_sequence_reports_omitted_items() -> None:
    observed = serialize_tool_observation(
        [{"id": index, "text": "value" * 20} for index in range(20)],
        max_tokens=MIN_OBSERVATION_TOKENS,
    )
    decoded = json.loads(observed)

    assert estimate_tokens(observed) <= MIN_OBSERVATION_TOKENS
    assert decoded["_observation"]["omitted_items"] > 0
    assert isinstance(decoded["data"], list)


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"tool_observation": "yes"}, "must be an object"),
        ({"tool_observation": {"max_tokens": True}}, "must be an integer"),
        ({"tool_observation": {"max_tokens": "many"}}, "must be an integer"),
        ({"tool_observation": {"max_tokens": -1}}, "zero or greater"),
        (
            {"tool_observation": {"max_tokens": MIN_OBSERVATION_TOKENS - 1}},
            "at least",
        ),
    ],
)
def test_invalid_observation_config_is_rejected(config: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_tool_observation_config(config)


def test_zero_budget_preserves_original_result() -> None:
    result = {"items": ["x" * 1000]}

    assert json.loads(serialize_tool_observation(result, max_tokens=0)) == result
    assert parse_tool_observation_config({}).max_tokens == 0


async def _large_tool(_arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "id": "result-1",
        "items": ["long result " * 100 for _ in range(10)],
    }


@pytest.mark.asyncio
async def test_adapter_persists_full_result_but_sends_bounded_observation() -> None:
    register_tool("large_observation_probe", _large_tool, overwrite=True)
    ctx = _RecordingContext()
    ctx.agent_config = {
        "model": "openai/gpt-4o-mini",
        "tools": ["large_observation_probe"],
        "tool_observation": {"max_tokens": 64},
        "graph": {
            "nodes": [{"id": "worker", "type": "agent"}],
            "edges": [["__start__", "worker"], ["worker", "__end__"]],
        },
    }

    result = await LangGraphAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    completed = [data for event, data in ctx.events if event == "tool_call.completed"]
    assert completed[0]["result"]["items"]
    tool_messages = [
        data for event, data in ctx.events if event == "message.created" and data["role"] == "tool"
    ]
    observed = json.loads(tool_messages[0]["content"])
    assert observed["_observation"]["truncated"] is True
    assert estimate_tokens(tool_messages[0]["content"]) <= 64


@pytest.mark.asyncio
async def test_explicit_tool_node_passes_preview_to_following_model() -> None:
    register_tool("large_observation_node", _large_tool, overwrite=True)
    ctx = _RecordingContext()
    ctx.agent_config = {
        "model": "openai/gpt-4o-mini",
        "tools": ["large_observation_node"],
        "tool_observation": {"max_tokens": 64},
        "graph": {
            "nodes": [
                {"id": "fetch", "type": "tool", "tool": "large_observation_node"},
                {"id": "reply", "type": "model"},
            ],
            "edges": [
                ["__start__", "fetch"],
                ["fetch", "reply"],
                ["reply", "__end__"],
            ],
        },
    }

    result = await LangGraphAdapter().run(ctx)

    assert result.status == RunStatus.SUCCEEDED
    reply = (result.output or {}).get("reply") or ""
    assert "truncated" in reply
    assert len(reply) < 1000
