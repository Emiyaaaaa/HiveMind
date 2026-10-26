"""Thread service — L1 conversation short memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import Agent, Message, Run, Thread
from app.runtime.memory_window import fit_messages_to_window, parse_memory_config
from app.runtime.messages import message_row_to_dict
from app.schemas.thread import (
    ThreadCreate,
    ThreadMessagePage,
    ThreadMessageRead,
)


class ThreadNotFound(Exception):
    def __init__(self, thread_id: str) -> None:
        self.thread_id = thread_id
        super().__init__(thread_id)


class AgentNotFound(Exception):
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(agent_id)


class ThreadService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_thread(
        self,
        payload: ThreadCreate,
        *,
        tenant_id: str,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> Thread:
        agent = await self.session.get(Agent, payload.agent_id)
        if (
            agent is None
            or agent.tenant_id != tenant_id
            or (project_id is not None and agent.project_id != project_id)
            or (agent_id is not None and agent.id != agent_id)
        ):
            raise AgentNotFound(payload.agent_id)

        resolved_project = payload.project_id or agent.project_id
        if project_id is not None and resolved_project != project_id:
            raise AgentNotFound(payload.agent_id)

        thread = Thread(
            tenant_id=agent.tenant_id,
            project_id=resolved_project,
            agent_id=agent.id,
            user_id=payload.user_id,
            title=payload.title,
        )
        self.session.add(thread)
        await self.session.commit()
        await self.session.refresh(thread)
        return thread

    async def get_thread(
        self,
        thread_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> Thread:
        thread = await self.session.get(Thread, thread_id)
        if thread is None:
            raise ThreadNotFound(thread_id)
        if tenant_id is not None and thread.tenant_id != tenant_id:
            raise ThreadNotFound(thread_id)
        # Match create_run: only reject when both sides declare a project and
        # they disagree. A null thread.project_id stays visible to project keys.
        if (
            project_id is not None
            and thread.project_id is not None
            and thread.project_id != project_id
        ):
            raise ThreadNotFound(thread_id)
        if agent_id is not None and thread.agent_id != agent_id:
            raise ThreadNotFound(thread_id)
        return thread

    async def list_threads(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[Thread]:
        capped = max(1, min(limit, 200))
        stmt = select(Thread).where(Thread.tenant_id == tenant_id)
        if project_id is not None:
            # Include unscoped threads (null project) for the same tenant.
            stmt = stmt.where(
                (Thread.project_id == project_id) | (Thread.project_id.is_(None))
            )
        if agent_id is not None:
            stmt = stmt.where(Thread.agent_id == agent_id)
        stmt = stmt.order_by(Thread.created_at.desc()).limit(capped)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_thread_messages(
        self,
        thread_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> ThreadMessagePage:
        await self.get_thread(
            thread_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        capped = max(1, min(limit, get_settings().run_messages_page_max))

        # Newest page first via DESC + limit, then reverse for ASC wire order.
        # Cursor keys use run.created_at (sort key), not message.created_at.
        stmt = (
            select(Message, Run)
            .join(Run, Message.run_id == Run.id)
            .where(Run.thread_id == thread_id)
            .order_by(Run.created_at.desc(), Message.index.desc(), Message.id.desc())
        )
        if cursor:
            parsed = _parse_message_cursor(cursor)
            if parsed is not None:
                run_created, index, msg_id = parsed
                stmt = stmt.where(
                    tuple_(Run.created_at, Message.index, Message.id)
                    < (run_created, index, msg_id)
                )

        result = await self.session.execute(stmt.limit(capped + 1))
        rows = list(result.all())
        has_more = len(rows) > capped
        page_rows = rows[:capped]
        page_rows.reverse()

        items = [
            ThreadMessageRead(
                id=msg.id,
                index=msg.index,
                step_id=msg.step_id,
                role=msg.role,
                name=msg.name,
                content=msg.content,
                tool_call_id=msg.tool_call_id,
                extra=msg.extra or {},
                created_at=msg.created_at,
                run_id=run.id,
            )
            for msg, run in page_rows
        ]
        next_cursor = None
        if has_more and page_rows:
            oldest_msg, oldest_run = page_rows[0]
            next_cursor = _message_cursor_key(
                oldest_run.created_at, oldest_msg.index, oldest_msg.id
            )

        return ThreadMessagePage(
            items=items, next_cursor=next_cursor, has_more=has_more
        )

    async def list_thread_runs(
        self,
        thread_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[Run]:
        await self.get_thread(
            thread_id,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
        )
        capped = max(1, min(limit, 200))
        stmt = (
            select(Run)
            .where(Run.thread_id == thread_id)
            .order_by(Run.created_at.asc())
            .limit(capped)
            .options(selectinload(Run.steps), selectinload(Run.checkpoints))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def load_thread_window(
        self,
        thread_id: str,
        *,
        exclude_run_id: str | None = None,
        agent_config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return OpenAI-style chat dicts for prior thread turns, window-trimmed.

        Seeds only complete user/assistant turns (no system / prompt_echo /
        reasoning / tool). Cross-run tool chains are incomplete and break model
        APIs, so they are omitted from L1. Reasoning blocks stay in the Run
        transcript for the console but are not replayed into the next prompt.
        Used by the worker when constructing ``AdapterContext``.
        """
        max_messages = get_settings().thread_messages_max
        # Over-fetch slightly so role filtering still fills the cap.
        fetch_limit = max_messages * 3 if max_messages > 0 else None

        stmt = (
            select(Message, Run)
            .join(Run, Message.run_id == Run.id)
            .where(Run.thread_id == thread_id)
            .where(Message.role.in_(("user", "assistant")))
            .order_by(
                Run.created_at.desc(),
                Run.id.desc(),
                Message.index.desc(),
                Message.id.desc(),
            )
        )
        if exclude_run_id is not None:
            stmt = stmt.where(Run.id != exclude_run_id)
        if fetch_limit is not None:
            stmt = stmt.limit(fetch_limit)

        result = await self.session.execute(stmt)
        messages: list[dict[str, Any]] = []
        for msg, _run in result.all():
            extra = msg.extra or {}
            if extra.get("kind") in ("prompt_echo", "reasoning", "attachment"):
                continue
            payload = message_row_to_dict(msg)
            # Drop incomplete tool-call metadata from prior runs.
            payload.pop("tool_calls", None)
            payload.pop("tool_call_id", None)
            if not str(payload.get("content") or "").strip():
                continue
            messages.append(payload)

        # Queried newest-first; restore chronological order for adapters.
        messages.reverse()

        if max_messages > 0 and len(messages) > max_messages:
            messages = messages[-max_messages:]

        memory_cfg = parse_memory_config(agent_config or {})
        if memory_cfg.window_tokens > 0:
            messages = fit_messages_to_window(
                messages,
                window_tokens=memory_cfg.window_tokens,
                summarize=memory_cfg.summarize,
            )
        return messages


def _message_cursor_key(run_created_at: datetime, index: int, message_id: str) -> str:
    return f"{run_created_at.isoformat()}|{index:08d}|{message_id}"


def _parse_message_cursor(
    cursor: str,
) -> tuple[datetime, int, str] | None:
    parts = cursor.split("|", 2)
    if len(parts) != 3:
        return None
    try:
        created = datetime.fromisoformat(parts[0])
        index = int(parts[1])
    except ValueError:
        return None
    return created, index, parts[2]
