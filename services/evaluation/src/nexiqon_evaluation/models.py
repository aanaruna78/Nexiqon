"""evaluation data (schema ``evaluation``): test sets and their cases, runs, per-case results,
outbox. RLS in 0001.

Results hold assistant answers produced with a content manager's view of the knowledge, so reading
them needs ``evaluation.results.view`` (editors and admins), not a plain ``read``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "evaluation"
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class EvalSet(TenantScopedMixin, Base):
    __tablename__ = "test_sets"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    name: Mapped[str] = mapped_column(String(63))
    agent: Mapped[str | None] = mapped_column(String(63), default=None, index=True)
    description: Mapped[str] = mapped_column(String(1000), default="")
    # manual | pack | conversations: where the cases first came from
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    # Evaluator plugin names; empty = every installed evaluator.
    evaluators: Mapped[list[str]] = mapped_column(_JSON, default=list)
    # Bumped on every case change: a gate only trusts runs made on the current cases.
    revision: Mapped[int] = mapped_column(Integer, default=1)


class EvalSetCase(TenantScopedMixin, Base):
    __tablename__ = "test_cases"

    test_set_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.test_sets.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(String(2000))
    lang: Mapped[str] = mapped_column(String(8), default="en")
    expected_source: Mapped[str | None] = mapped_column(String(500), default=None)
    expected_section: Mapped[str | None] = mapped_column(String(500), default=None)
    expected_phrases: Mapped[list[str]] = mapped_column(_JSON, default=list)
    must_abstain: Mapped[bool] = mapped_column(Boolean, default=False)
    # Where the case came from, e.g. {"kind": "run", "ref": "<agent run id>"} (fix loop, ST-14).
    origin: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    notes: Mapped[str] = mapped_column(String(1000), default="")


class EvalRun(TenantScopedMixin, Base):
    __tablename__ = "runs"

    agent: Mapped[str] = mapped_column(String(63), index=True)
    version: Mapped[int] = mapped_column(Integer)
    test_set_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.test_sets.id", ondelete="CASCADE"), index=True
    )
    test_set_revision: Mapped[int] = mapped_column(Integer)
    # The assistant version's content when the run started (drafts change in place): a gate
    # only trusts a run of exactly the content being published.
    spec_hash: Mapped[str] = mapped_column(String(64))
    # queued | running | completed | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    started_by: Mapped[str] = mapped_column(String(200))
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    done_count: Mapped[int] = mapped_column(Integer, default=0)
    scorecard: Mapped[dict[str, Any] | None] = mapped_column(_JSON, default=None)
    error: Mapped[str | None] = mapped_column(String(1000), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class EvalResult(TenantScopedMixin, Base):
    __tablename__ = "results"
    __table_args__ = (UniqueConstraint("run_id", "case_id"),)

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[UUID] = mapped_column(index=True)
    question: Mapped[str] = mapped_column(String(2000))
    lang: Mapped[str] = mapped_column(String(8), default="en")
    answer: Mapped[str] = mapped_column(Text, default="")
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str | None] = mapped_column(String(32), default=None)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(_JSON, default=list)
    # {evaluator: {"value": 0..1, "passed": bool, "detail": str}}
    scores: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    agent_run_id: Mapped[str | None] = mapped_column(String(64), default=None)
    error: Mapped[str | None] = mapped_column(String(1000), default=None)


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
