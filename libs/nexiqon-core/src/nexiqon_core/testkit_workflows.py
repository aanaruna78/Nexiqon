"""Sample tenant-scoped workflow used by the chassis tests (Temporal's sandbox needs an importable
module). Not used at runtime."""

from __future__ import annotations

from datetime import timedelta

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    import uuid

    from sqlalchemy import String, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    from nexiqon_core.db import TenantScopedMixin, TenantSessionFactory, service_metadata
    from nexiqon_core.workflows import TenantScope

SCHEMA = "workflow_test"
SESSIONS: dict[str, TenantSessionFactory] = {}


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class Note(TenantScopedMixin, Base):
    __tablename__ = "notes"
    body: Mapped[str] = mapped_column(String(100))


@activity.defn
async def read_note(scope: TenantScope, note_id: str) -> str | None:
    """Data access uses only the workflow's tenant scope."""
    async with SESSIONS["db"].session(scope.context()) as s:
        body: str | None = await s.scalar(select(Note.body).where(Note.id == uuid.UUID(note_id)))
        return body


@workflow.defn
class ReadNote:
    @workflow.run
    async def run(self, scope: TenantScope, note_id: str) -> str | None:
        result: str | None = await workflow.execute_activity(
            read_note, args=[scope, note_id], start_to_close_timeout=timedelta(seconds=10)
        )
        return result
