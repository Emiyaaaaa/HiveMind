"""Thread service — L1 conversation short memory."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
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
        if project_id is not None and thread.project_id != project_id:
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
            stmt = stmt.where(Thread.project_id == project_id)
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

        stmt = (
            select(Message, Run)
            .join(Run, Message.run_id == Run.id)
            .where(Run.thread_id == thread_id)
            .order_by(Run.created_at.asc(), Message.index.asc(), Message.id.asc())
        )
        result = await self.session.execute(stmt)
        rows = list(result.all())

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
            for msg, run in rows
        ]

        # Cursor = exclusive lower bound encoded as created_at|index|id of the
        # oldest item on the previous (newer) page. For simplicity we page from
        # the end (newest first window) like run messages.
        if cursor:
            items = [m for m in items if _message_cursor_key(m) < cursor]

        # Newest page: take last N, then report has_more for older ones.
        has_more = len(items) > capped
        if has_more:
            page = items[-capped:]
            next_cursor = _message_cursor_key(page[0])
        else:
            page = items
            next_cursor = None

        return ThreadMessagePage(
            items=page, next_cursor=next_cursor, has_more=has_more
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

        Skips prompt_echo / system rows so adapters can attach their own system
        prompt. Used by the worker when constructing ``AdapterContext``.
        """
        stmt = (
            select(Message, Run)
            .join(Run, Message.run_id == Run.id)
            .where(Run.thread_id == thread_id)
            .order_by(Run.created_at.asc(), Run.id.asc(), Message.index.asc(), Message.id.asc())
        )
        if exclude_run_id is not None:
            stmt = stmt.where(Run.id != exclude_run_id)

        result = await self.session.execute(stmt)
        messages: list[dict[str, Any]] = []
        for msg, _run in result.all():
            extra = msg.extra or {}
            if extra.get("kind") == "prompt_echo":
                continue
            if msg.role == "system":
                continue
            messages.append(message_row_to_dict(msg))

        memory_cfg = parse_memory_config(agent_config or {})
        max_messages = get_settings().thread_messages_max
        if max_messages > 0 and len(messages) > max_messages:
            messages = messages[-max_messages:]

        if memory_cfg.window_tokens > 0:
            messages = fit_messages_to_window(
                messages,
                window_tokens=memory_cfg.window_tokens,
                summarize=memory_cfg.summarize,
            )
        return messages


def _message_cursor_key(msg: ThreadMessageRead) -> str:
    return f"{msg.created_at.isoformat()}|{msg.index:08d}|{msg.id}"
