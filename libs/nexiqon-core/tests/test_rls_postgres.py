"""Integration: RLS isolation on real PostgreSQL (pgvector image). Needs Docker."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import String, select, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from nexiqon_core.db import (
    Base,
    TenantScopedMixin,
    TenantSessionFactory,
    create_engine,
    rls_policy_sql,
)
from nexiqon_core.events import InMemoryPublisher, OutboxEvent, OutboxRelay, add_event
from nexiqon_core.testing import TwoTenants

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not available"),
]

APP_ROLE = "nexiqon_app"
APP_PASSWORD = "app-password"


class Note(TenantScopedMixin, Base):
    __tablename__ = "notes"
    body: Mapped[str] = mapped_column(String(200))


@pytest.fixture(scope="module")
def pg_url() -> str:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture
async def engines(pg_url: str) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    """(owner_engine, app_engine). The app role does not own the tables, like production."""
    owner = create_engine(pg_url)
    async with owner.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        for stmt in rls_policy_sql("notes"):
            await conn.execute(text(stmt))
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE}
        )
        if not exists:
            await conn.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
        await conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON notes, outbox_events TO {APP_ROLE}")
        )
    user_part = pg_url.split("://", 1)[1].split("@", 1)[0]
    app_url = pg_url.replace(user_part, f"{APP_ROLE}:{APP_PASSWORD}", 1)
    app = create_engine(app_url)
    yield owner, app
    await app.dispose()
    await owner.dispose()


async def test_tenant_cannot_read_or_write_other_tenant(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    _, app = engines
    tenants = TwoTenants.create()
    sessions = TenantSessionFactory(app)

    async with sessions.session(tenants.a.context) as s:
        s.add(Note(tenant_id=tenants.a.context.tenant_id, body="a-secret"))
    async with sessions.session(tenants.b.context) as s:
        s.add(Note(tenant_id=tenants.b.context.tenant_id, body="b-secret"))

    async with sessions.session(tenants.a.context) as s:
        bodies = (await s.execute(select(Note.body))).scalars().all()
    assert bodies == ["a-secret"]

    # Writing a row for another tenant violates WITH CHECK.
    with pytest.raises(Exception, match="row-level security"):
        async with sessions.session(tenants.a.context) as s:
            s.add(Note(tenant_id=tenants.b.context.tenant_id, body="forged"))

    # No context at all: nothing visible.
    async with sessions.system_session() as s:
        assert (await s.execute(select(Note))).scalars().all() == []


async def test_context_does_not_leak_through_pool(engines: tuple[AsyncEngine, AsyncEngine]) -> None:
    _, app = engines
    tenants = TwoTenants.create()
    sessions = TenantSessionFactory(app)
    async with sessions.session(tenants.a.context) as s:
        s.add(Note(tenant_id=tenants.a.context.tenant_id, body="x"))
    for _ in range(5):  # reuse pooled connections
        async with sessions.system_session() as s:
            setting = await s.scalar(text("SELECT current_setting('app.tenant_id', true)"))
            assert setting in (None, "")


async def test_outbox_commits_with_business_write(engines: tuple[AsyncEngine, AsyncEngine]) -> None:
    _, app = engines
    tenants = TwoTenants.create()
    sessions = TenantSessionFactory(app)
    async with sessions.session(tenants.a.context) as s:
        s.add(Note(tenant_id=tenants.a.context.tenant_id, body="y"))
        add_event(s, tenants.a.context, source="notes", type="nexiqon.notes.note.created", data={})

    # A failed transaction leaves no event behind.
    with pytest.raises(RuntimeError):
        async with sessions.session(tenants.a.context) as s:
            add_event(
                s, tenants.a.context, source="notes", type="nexiqon.notes.note.created", data={}
            )
            raise RuntimeError("boom")

    publisher = InMemoryPublisher()
    async with sessions.system_session() as s:
        assert await OutboxRelay(publisher).relay_once(s) >= 1
    async with sessions.system_session() as s:
        assert await OutboxRelay(publisher).relay_once(s) == 0
    assert all(e["type"] == "nexiqon.notes.note.created" for e in publisher.events)
    assert OutboxEvent.__tablename__ == "outbox_events"
