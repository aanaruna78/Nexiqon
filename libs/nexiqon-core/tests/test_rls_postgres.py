"""Integration: RLS isolation on real PostgreSQL (shared session container). Needs Docker."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import String, select, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import (
    TenantScopedMixin,
    TenantSessionFactory,
    create_engine,
    extra_policy_sql,
    rls_policy_sql,
    service_metadata,
    setting,
)
from nexiqon_core.events import InMemoryPublisher, OutboxMixin, OutboxRelay, add_event
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.testing import TwoTenants

pytestmark = pytest.mark.integration
SCHEMA = "chassis_test"


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class Note(TenantScopedMixin, Base):
    __tablename__ = "notes"
    body: Mapped[str] = mapped_column(String(200))
    owner: Mapped[str] = mapped_column(String(50), default="")


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"


@pytest.fixture
async def app_engine(postgres: PgUrls) -> AsyncIterator[AsyncEngine]:
    owner = create_engine(postgres.owner)
    async with owner.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
        statements = rls_policy_sql("notes", SCHEMA) + extra_policy_sql(
            "notes",
            SCHEMA,
            "owner_reads_own",
            f"owner = {setting('owner', 'text')}",
            command="SELECT",
        )
        for stmt in statements:
            await conn.execute(text(stmt))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {postgres.app_role}"))
        await conn.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO {postgres.app_role}"
            )
        )
    await owner.dispose()
    app = create_engine(postgres.app)
    yield app
    await app.dispose()


async def test_tenant_cannot_read_or_write_other_tenant(app_engine: AsyncEngine) -> None:
    tenants = TwoTenants.create()
    sessions = TenantSessionFactory(app_engine)

    async with sessions.session(tenants.a.context) as s:
        s.add(Note(tenant_id=tenants.a.context.tenant_id, body="a-secret"))
    async with sessions.session(tenants.b.context) as s:
        s.add(Note(tenant_id=tenants.b.context.tenant_id, body="b-secret"))

    async with sessions.session(tenants.a.context) as s:
        assert (await s.execute(select(Note.body))).scalars().all() == ["a-secret"]

    with pytest.raises(Exception, match="row-level security"):
        async with sessions.session(tenants.a.context) as s:
            s.add(Note(tenant_id=tenants.b.context.tenant_id, body="forged"))

    async with sessions.system_session() as s:
        assert (await s.execute(select(Note))).scalars().all() == []


async def test_extra_policy_grants_narrow_cross_tenant_read(app_engine: AsyncEngine) -> None:
    tenants = TwoTenants.create()
    sessions = TenantSessionFactory(app_engine)
    for actor in (tenants.a, tenants.b):
        async with sessions.session(actor.context) as s:
            s.add(Note(tenant_id=actor.context.tenant_id, body="x", owner="alice"))
            s.add(Note(tenant_id=actor.context.tenant_id, body="y", owner="bob"))
    async with sessions.scoped({"owner": "alice"}) as s:
        rows = (await s.execute(select(Note.owner))).scalars().all()
    assert rows == ["alice", "alice"]  # alice's rows in both tenants, nothing else


async def test_context_does_not_leak_through_pool(app_engine: AsyncEngine) -> None:
    tenants = TwoTenants.create()
    sessions = TenantSessionFactory(app_engine)
    async with sessions.session(tenants.a.context) as s:
        s.add(Note(tenant_id=tenants.a.context.tenant_id, body="x"))
    for _ in range(5):
        async with sessions.system_session() as s:
            value = await s.scalar(text("SELECT current_setting('app.tenant_id', true)"))
            assert value in (None, "")


async def test_outbox_commits_with_business_write(app_engine: AsyncEngine) -> None:
    tenants = TwoTenants.create()
    sessions = TenantSessionFactory(app_engine)
    async with sessions.session(tenants.a.context) as s:
        s.add(Note(tenant_id=tenants.a.context.tenant_id, body="y"))
        add_event(
            s, Outbox, tenants.a.context, source="notes", type="nexiqon.notes.note.created", data={}
        )

    with pytest.raises(RuntimeError):
        async with sessions.session(tenants.a.context) as s:
            add_event(
                s,
                Outbox,
                tenants.a.context,
                source="notes",
                type="nexiqon.notes.note.created",
                data={},
            )
            raise RuntimeError("boom")

    publisher = InMemoryPublisher()
    async with sessions.system_session() as s:
        assert await OutboxRelay(publisher, Outbox).relay_once(s) == 1
    async with sessions.system_session() as s:
        assert await OutboxRelay(publisher, Outbox).relay_once(s) == 0
    assert publisher.events[0]["type"] == "nexiqon.notes.note.created"
