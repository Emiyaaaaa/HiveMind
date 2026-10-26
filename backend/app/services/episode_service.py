"""Write a short episode when a Run finishes, and recall it into the next one.

Recall is recency plus token overlap (including CJK characters). Embeddings
and ``memory.*`` tools are intentionally out of scope.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import MemoryHit
from app.models.memory import MemoryItem
from app.models.run import Message, Run, RunStatus, Step, ToolCall

SCOPES = frozenset({"thread", "agent", "project", "user"})
KINDS = frozenset({"episode", "fact", "document_chunk", "procedure"})
_RECALL_LIMIT = 3
_CANDIDATES = 40
_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


class MemoryNotFound(Exception):
    pass


class MemoryRejected(Exception):
    pass


def prompt_text(data: dict[str, Any] | None) -> str:
    if not data:
        return ""
    for key in ("prompt", "message", "text", "input", "task"):
        if key in data:
            value = data[key]
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return ""


def render_episode_block(hits: list[MemoryHit]) -> dict[str, str]:
    """System turn seeded into the next Run. Ids stay in message ``extra``."""
    lines = ["Earlier episodes (summary only, not the full transcript):"]
    lines.extend(f"- {hit.content}" for hit in hits)
    return {"role": "system", "content": "\n".join(lines)}


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN.finditer(text)}


def _score(query: str, content: str, rank: int) -> float:
    """``rank`` 0 is the newest candidate. Empty queries fall back to recency."""
    recency = 1.0 / (1 + rank)
    query_tokens = _tokens(query)
    if not query_tokens:
        return recency
    overlap = len(query_tokens & _tokens(content)) / len(query_tokens)
    return overlap * 0.7 + recency * 0.3


class EpisodeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest_run(self, run: Run) -> MemoryItem | None:
        """Replace this run's episode. Caller commits. No-op unless finished."""
        if run.status not in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            return None
        await self.session.execute(
            delete(MemoryItem).where(
                MemoryItem.source_run_id == run.id,
                MemoryItem.kind == "episode",
            )
        )
        item = MemoryItem(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            agent_id=run.agent_id,
            thread_id=run.thread_id,
            scope="thread" if run.thread_id else "agent",
            kind="episode",
            content=await self._summarize(run),
            source_run_id=run.id,
            metadata_={"outcome": str(run.status)},
        )
        self.session.add(item)
        return item

    async def recall(
        self,
        *,
        tenant_id: str,
        agent_id: str | None,
        thread_id: str | None,
        query: str,
        limit: int = _RECALL_LIMIT,
    ) -> list[MemoryHit]:
        """Episodes for this thread, or this agent when the run has no thread."""
        stmt = select(MemoryItem).where(
            MemoryItem.tenant_id == tenant_id,
            MemoryItem.kind == "episode",
            or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > datetime.now(UTC)),
        )
        if thread_id:
            stmt = stmt.where(
                MemoryItem.scope == "thread", MemoryItem.thread_id == thread_id
            )
        elif agent_id:
            stmt = stmt.where(
                MemoryItem.scope == "agent", MemoryItem.agent_id == agent_id
            )
        else:
            return []
        stmt = stmt.order_by(MemoryItem.created_at.desc()).limit(_CANDIDATES)
        rows = list((await self.session.scalars(stmt)).all())
        return _hits(rows, query, limit)

    async def search(
        self,
        *,
        tenant_id: str,
        query: str = "",
        scope: str | None = None,
        kind: str | None = None,
        thread_id: str | None = None,
        agent_id: str | None = None,
        project_id: str | None = None,
        limit: int = 20,
    ) -> list[tuple[MemoryItem, float]]:
        stmt = select(MemoryItem).where(
            MemoryItem.tenant_id == tenant_id,
            or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > datetime.now(UTC)),
        )
        if scope:
            stmt = stmt.where(MemoryItem.scope == scope)
        if kind:
            stmt = stmt.where(MemoryItem.kind == kind)
        if thread_id:
            stmt = stmt.where(MemoryItem.thread_id == thread_id)
        if agent_id:
            stmt = stmt.where(MemoryItem.agent_id == agent_id)
        if project_id:
            stmt = stmt.where(MemoryItem.project_id == project_id)
        stmt = stmt.order_by(MemoryItem.created_at.desc()).limit(_CANDIDATES)
        rows = list((await self.session.scalars(stmt)).all())
        ranked = sorted(
            ((row, _score(query, row.content, index)) for index, row in enumerate(rows)),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return ranked[: max(1, min(limit, 50))]

    async def store(
        self,
        *,
        tenant_id: str,
        content: str,
        kind: str = "fact",
        scope: str | None = None,
        agent_id: str | None = None,
        thread_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        text = content.strip()
        if not text:
            raise MemoryRejected("content is empty")
        if kind not in KINDS:
            raise MemoryRejected(f"kind must be one of {sorted(KINDS)}")
        resolved = scope or ("thread" if thread_id else "agent" if agent_id else "")
        if resolved not in SCOPES:
            raise MemoryRejected("scope is required (thread, agent, project, or user)")
        if resolved == "thread" and not thread_id:
            raise MemoryRejected("thread scope requires thread_id")
        if resolved == "agent" and not agent_id:
            raise MemoryRejected("agent scope requires agent_id")
        if resolved == "project" and not project_id:
            raise MemoryRejected("project scope requires project_id")
        if resolved == "user" and not user_id:
            raise MemoryRejected("user scope requires user_id")
        item = MemoryItem(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
            thread_id=thread_id,
            user_id=user_id,
            scope=resolved,
            kind=kind,
            content=_clip(text, 8000),
            metadata_=dict(metadata or {}),
            expires_at=expires_at,
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(
        self,
        memory_id: str,
        *,
        tenant_id: str,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        stmt = select(MemoryItem).where(
            MemoryItem.id == memory_id, MemoryItem.tenant_id == tenant_id
        )
        if project_id is not None:
            stmt = stmt.where(MemoryItem.project_id == project_id)
        if agent_id is not None:
            stmt = stmt.where(MemoryItem.agent_id == agent_id)
        item = (await self.session.scalars(stmt)).first()
        if item is None:
            raise MemoryNotFound(memory_id)
        await self.session.delete(item)
        await self.session.commit()

    async def _summarize(self, run: Run) -> str:
        messages = list(
            (
                await self.session.scalars(
                    select(Message)
                    .where(Message.run_id == run.id)
                    .order_by(Message.index)
                )
            ).all()
        )
        user_bits = [
            message.content
            for message in messages
            if message.role == "user" and (message.extra or {}).get("kind") != "memory"
        ]
        replies = [message.content for message in messages if message.role == "assistant"]
        tool_bits: list[str] = []
        tools = (
            await self.session.scalars(
                select(ToolCall).join(Step, ToolCall.step_id == Step.id).where(Step.run_id == run.id)
            )
        ).all()
        for call in tools:
            if call.error:
                detail = call.error
            elif call.result is not None:
                detail = json.dumps(call.result, ensure_ascii=False, default=str)
            else:
                detail = ""
            tool_bits.append(f"{call.name}({_clip(detail, 80)})")

        user_text = _clip(" ".join(user_bits) or prompt_text(run.input), 400)
        if replies:
            output_text = _clip(" ".join(replies), 400)
        elif run.status == RunStatus.FAILED and run.error:
            output_text = _clip(run.error, 400)
        elif run.output:
            output_text = _clip(json.dumps(run.output, ensure_ascii=False, default=str), 400)
        else:
            output_text = ""
        parts = [f"outcome={run.status}", f"input: {user_text}", f"output: {output_text}"]
        if tool_bits:
            parts.append("tools: " + _clip("; ".join(tool_bits), 200))
        return _clip("\n".join(parts), 1200)


def _hits(rows: list[MemoryItem], query: str, limit: int) -> list[MemoryHit]:
    ranked = sorted(
        (
            (
                row,
                _score(query, row.content, index),
            )
            for index, row in enumerate(rows)
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [
        MemoryHit(
            id=row.id,
            content=row.content,
            score=score,
            source_run_id=row.source_run_id,
            kind=row.kind,
        )
        for row, score in ranked[: max(1, limit)]
    ]


class EpisodeErasureHook:
    """Drop episode rows when a run or tenant is erased."""

    async def erase_run(self, session: AsyncSession, run: Run) -> dict[str, int]:
        result = await session.execute(
            delete(MemoryItem).where(MemoryItem.source_run_id == run.id)
        )
        return {"memory_items_deleted": int(result.rowcount or 0)}

    async def erase_tenant(self, session: AsyncSession, tenant_id: str) -> dict[str, int]:
        result = await session.execute(
            delete(MemoryItem).where(MemoryItem.tenant_id == tenant_id)
        )
        return {"memory_items_deleted": int(result.rowcount or 0)}
