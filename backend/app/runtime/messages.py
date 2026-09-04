"""Helpers for rebuilding LangGraph message windows from persisted rows."""

from __future__ import annotations

from typing import Any

from app.models.run import Message


def message_row_to_dict(msg: Message) -> dict[str, Any]:
    """Convert a persisted ``Message`` row to an OpenAI-style chat dict."""
    payload: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.name:
        payload["name"] = msg.name
    if msg.tool_call_id:
        payload["tool_call_id"] = msg.tool_call_id
    extra = msg.extra or {}
    tool_calls = extra.get("tool_calls")
    if tool_calls:
        payload["tool_calls"] = tool_calls
    attachments = extra.get("attachments")
    if attachments:
        # Keep refs for adapters that rebuild multimodal content; binary stays
        # in object storage and is loaded on demand.
        payload["extra"] = {"attachments": attachments}
        if extra.get("kind"):
            payload["extra"]["kind"] = extra["kind"]
    return payload


def messages_from_rows(rows: list[Message]) -> list[dict[str, Any]]:
    return [message_row_to_dict(row) for row in rows]
