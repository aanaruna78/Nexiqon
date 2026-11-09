"""agent-runtime data (schema ``agent_runtime``): threads, runs (traces) and LangGraph checkpoints.

Every table is tenant-scoped with forced RLS, including the checkpoints that hold conversation
state: a checkpoint can only ever be read back by the tenant that wrote it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata

SCHEMA = "agent_runtime"
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class Thread(TenantScopedMixin, Base):
    """One conversation's agent state; owned by the actor who started it."""

    __tablename__ = "threads"
    __table_args__ = (UniqueConstraint("tenant_id", "thread_id"),)

    thread_id: Mapped[str] = mapped_column(String(100))
    agent: Mapped[str] = mapped_column(String(63))
    actor_id: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(24), default="idle"
    )  # idle | awaiting_input | awaiting_approval | escalated


class Run(TenantScopedMixin, Base):
    """One turn or resume: the steps taken, for the Answer Inspector. No secrets, no tokens."""

    __tablename__ = "runs"

    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    agent: Mapped[str] = mapped_column(String(63))
    agent_versions: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    kind: Mapped[str] = mapped_column(String(16))  # turn | resume
    status: Mapped[str] = mapped_column(
        String(16), default="running"
    )  # running | completed | interrupted | failed
    steps: Mapped[list[dict[str, Any]]] = mapped_column(_JSON, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(1000), default=None)
    actor_id: Mapped[str] = mapped_column(String(200))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Checkpoint(TenantScopedMixin, Base):
    __tablename__ = "checkpoints"
    __table_args__ = (UniqueConstraint("tenant_id", "thread_id", "checkpoint_ns", "checkpoint_id"),)

    thread_id: Mapped[str] = mapped_column(String(100))
    checkpoint_ns: Mapped[str] = mapped_column(String(200), default="")
    checkpoint_id: Mapped[str] = mapped_column(String(64))
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(64), default=None)
    type: Mapped[str] = mapped_column(String(32))
    checkpoint: Mapped[bytes] = mapped_column(LargeBinary)
    metadata_type: Mapped[str] = mapped_column(String(32))
    meta: Mapped[bytes] = mapped_column(LargeBinary)


class CheckpointBlob(TenantScopedMixin, Base):
    __tablename__ = "checkpoint_blobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "thread_id", "checkpoint_ns", "channel", "version"),
    )

    thread_id: Mapped[str] = mapped_column(String(100))
    checkpoint_ns: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))
    blob: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)


class CheckpointWrite(TenantScopedMixin, Base):
    __tablename__ = "checkpoint_writes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"
        ),
    )

    thread_id: Mapped[str] = mapped_column(String(100))
    checkpoint_ns: Mapped[str] = mapped_column(String(200), default="")
    checkpoint_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    task_path: Mapped[str] = mapped_column(String(500), default="")
    idx: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(32))
    blob: Mapped[bytes] = mapped_column(LargeBinary)
