"""Helpers for multimodal attachments in adapter prompts and SSE."""

from __future__ import annotations

import base64
from typing import Any

from app.adapters.base import AdapterContext
from app.models.attachment import Attachment
from app.runtime.object_store import ObjectStore, get_object_store
from app.schemas.attachment import attachment_ref


def is_image_media_type(media_type: str) -> bool:
    return media_type.lower().startswith("image/")


async def load_attachment_bytes(
    attachment: Attachment,
    *,
    store: ObjectStore | None = None,
) -> bytes:
    return await (store or get_object_store()).get(attachment.storage_key)


def data_url(media_type: str, data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


async def openai_user_content(
    text: str,
    attachments: list[Attachment],
    *,
    store: ObjectStore | None = None,
) -> str | list[dict[str, Any]]:
    """Build OpenAI chat ``content`` — multimodal list when images are present."""
    image_parts: list[dict[str, Any]] = []
    notes: list[str] = []
    for attachment in attachments:
        if is_image_media_type(attachment.media_type):
            blob = await load_attachment_bytes(attachment, store=store)
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url(attachment.media_type, blob),
                    },
                }
            )
        else:
            caption = attachment.caption or attachment.filename
            notes.append(
                f"[attachment {attachment.id} {attachment.media_type} {caption}]"
            )

    body = text or ""
    if notes:
        body = (body + "\n\n" if body else "") + "\n".join(notes)

    if not image_parts:
        return body

    parts: list[dict[str, Any]] = [{"type": "text", "text": body or "(image)"}]
    parts.extend(image_parts)
    return parts


async def emit_input_attachments(
    ctx: AdapterContext,
    attachments: list[Attachment],
    *,
    step_index: int | None = None,
    role: str = "user",
) -> list[dict[str, Any]]:
    """Stream fine-grained attachment deltas, then persist a message with refs.

    Returns the compact refs stored on ``Message.extra.attachments``.
    """
    if not attachments:
        return []

    refs = [attachment_ref(a) for a in attachments]
    for ref in refs:
        await ctx.emit_token_delta(
            step_index=step_index if step_index is not None else 0,
            delta=str(ref.get("filename") or ref.get("id") or ""),
            role=role,
            part="attachment",
            attachment=ref,
        )

    captions = [str(a.caption or a.filename) for a in attachments]
    content = "; ".join(captions) if captions else f"{len(attachments)} attachment(s)"
    await ctx.emit_message(
        role=role,
        content=content,
        step_index=step_index,
        kind="attachment",
        attachments=refs,
    )
    return refs


def message_dict_with_attachments(msg: dict[str, Any]) -> dict[str, Any]:
    """Keep attachment refs on chat dicts reconstructed from Message rows."""
    payload = dict(msg)
    extra = payload.get("extra") or {}
    attachments = extra.get("attachments")
    if attachments:
        payload["attachments"] = attachments
    return payload
