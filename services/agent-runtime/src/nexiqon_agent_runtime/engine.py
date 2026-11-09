"""Runs a turn (or resumes an interrupted one) of an agent on a conversation thread."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from sqlalchemy import select

from nexiqon_agent_runtime.checkpointer import TenantCheckpointer
from nexiqon_agent_runtime.clients import Models, Retrieval, ServiceReads, Tools
from nexiqon_agent_runtime.graph import compile_graph
from nexiqon_agent_runtime.models import Run, Thread
from nexiqon_agent_runtime.nodes import RunContext
from nexiqon_agent_runtime.settings import ServiceSettings
from nexiqon_agent_runtime.spec import validate_graph
from nexiqon_agent_runtime.state import fresh_turn
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import Conflict, Forbidden
from nexiqon_core.tenancy import TenantContext

log = structlog.get_logger(__name__)
STAFF_ROLES = ("owner", "admin")


@dataclass
class TurnResult:
    run_id: uuid.UUID
    status: str  # completed | interrupted | failed
    answer: dict[str, Any] | None = None
    interrupt: dict[str, Any] | None = None
    handoff: dict[str, Any] | None = None
    intent: str | None = None
    route: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    retention_profile: str | None = None


class Engine:
    def __init__(
        self,
        settings: ServiceSettings,
        db: TenantSessionFactory,
        reads: ServiceReads,
        models: Models,
        retrieval: Retrieval,
        tools: Tools,
    ) -> None:
        self.settings = settings
        self.db = db
        self.reads = reads
        self.models = models
        self.retrieval = retrieval
        self.tools = tools

    async def _thread(self, ctx: TenantContext, thread_id: str, agent: str) -> Thread:
        async with self.db.session(ctx) as s:
            thread = await s.scalar(select(Thread).where(Thread.thread_id == thread_id))
            if thread is None:
                thread = Thread(
                    tenant_id=ctx.tenant_id,
                    thread_id=thread_id,
                    agent=agent,
                    actor_id=ctx.actor_id,
                    status="idle",
                )
                s.add(thread)
                await s.flush()
            elif thread.actor_id != ctx.actor_id and not ctx.has_role(*STAFF_ROLES):
                raise Forbidden("This conversation belongs to someone else")
            elif thread.agent != agent:
                raise Conflict(f"This conversation is with agent {thread.agent!r}")
            return thread

    async def run(
        self,
        ctx: TenantContext,
        token: str,
        agent_name: str,
        thread_id: str,
        *,
        text: str | None,
        resume: Any = None,
        history: list[dict[str, str]] | None = None,
        locale: str = "en",
    ) -> TurnResult:
        resolved = await self.reads.agent(ctx.tenant_id, agent_name)
        spec = validate_graph(resolved["graph"])
        thread = await self._thread(ctx, thread_id, agent_name)
        if thread.status == "awaiting_approval" and resume is None:
            raise Conflict("Waiting for an approval decision on this conversation")
        resuming = thread.status in ("awaiting_input", "awaiting_approval")
        if resuming and resume is None:
            resume = text  # the user's reply answers the clarifying question
        if not resuming and text is None:
            raise Conflict("Nothing to resume on this conversation")
        names = list(
            ((resolved.get("config") or {}).get("knowledge") or {}).get("collections") or []
        )
        collection_ids = await self.reads.collection_ids(ctx.tenant_id, names) if names else []
        async with self.db.session(ctx) as s:
            run_row = Run(
                tenant_id=ctx.tenant_id,
                thread_id=thread_id,
                agent=agent_name,
                agent_versions=resolved.get("versions") or {},
                kind="resume" if resuming else "turn",
                actor_id=ctx.actor_id,
            )
            s.add(run_row)
            await s.flush()
            run_id = run_row.id
        context = RunContext(
            token=token,
            thread_id=thread_id,
            agent=resolved,
            collection_ids=collection_ids,
            models=self.models,
            retrieval=self.retrieval,
            tools=self.tools,
            run_id=str(run_id),
        )
        app = compile_graph(spec, context, TenantCheckpointer(self.db, ctx))
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.settings.max_steps,
        }
        payload: Any = (
            Command(resume=resume)
            if resuming
            else fresh_turn(
                text or "", list(history or [])[-self.settings.history_messages :], locale
            )
        )
        result = TurnResult(
            run_id=run_id,
            status="failed",
            retention_profile=(resolved.get("config") or {}).get("retention_profile"),
        )
        try:
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                state = await app.ainvoke(payload, config)
        except GraphRecursionError:
            result.error = "The agent took too many steps; the graph may loop"
            state = {}
        except TimeoutError:
            result.error = "The agent did not finish in time"
            state = {}
        except Exception as exc:  # recorded on the run; the caller gets a clear failure
            log.warning("agent_run_failed", run_id=str(run_id), error=str(exc))
            result.error = str(exc)[:1000]
            state = {}
        interrupts = state.get("__interrupt__") if state else None
        if interrupts:
            result.status = "interrupted"
            result.interrupt = dict(interrupts[0].value or {})
        elif state:
            result.status = "completed"
        result.answer = state.get("answer") if state and not interrupts else None
        result.handoff = state.get("handoff") if state else None
        result.intent, result.route = state.get("intent"), state.get("route")
        result.steps = list(state.get("steps") or []) if state else []
        new_status = (
            (
                "awaiting_input"
                if (result.interrupt or {}).get("kind") == "clarify"
                else "awaiting_approval"
            )
            if result.status == "interrupted"
            else ("escalated" if result.handoff else "idle")
        )
        if result.status == "failed":
            new_status = thread.status  # a failed run leaves the conversation where it was
        async with self.db.session(ctx) as s:
            row = await s.get(Run, run_id)
            stored = await s.scalar(select(Thread).where(Thread.thread_id == thread_id))
            assert row is not None
            assert stored is not None
            row.status, row.steps, row.error = result.status, result.steps, result.error
            row.result = {
                "answer": result.answer,
                "interrupt": result.interrupt,
                "handoff": result.handoff,
                "intent": result.intent,
                "route": result.route,
            }
            row.finished_at = datetime.now(UTC)
            stored.status = new_status
        return result
