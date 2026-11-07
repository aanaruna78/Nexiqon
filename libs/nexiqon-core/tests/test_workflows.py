"""Integration: a Temporal workflow scoped to tenant A cannot read tenant B's data (RLS)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from nexiqon_core.db import TenantSessionFactory, create_engine, rls_policy_sql
from nexiqon_core.errors import BadRequest
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.testing import TwoTenants
from nexiqon_core.testkit_workflows import SCHEMA, SESSIONS, Base, Note, ReadNote, read_note
from nexiqon_core.workflows import TenantScope, workflow_id

pytestmark = pytest.mark.integration


@pytest.fixture
async def sessions(postgres: PgUrls) -> AsyncIterator[TenantSessionFactory]:
    owner = create_engine(postgres.owner)
    async with owner.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
        for stmt in rls_policy_sql("notes", SCHEMA):
            await conn.execute(text(stmt))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {postgres.app_role}"))
        await conn.execute(
            text(f"GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA {SCHEMA} TO {postgres.app_role}")
        )
    await owner.dispose()
    app = create_engine(postgres.app)
    SESSIONS["db"] = TenantSessionFactory(app)
    yield SESSIONS["db"]
    await app.dispose()


async def test_workflow_is_confined_to_its_tenant(sessions: TenantSessionFactory) -> None:
    t = TwoTenants.create()
    ids: dict[str, str] = {}
    for label, actor in (("a", t.a), ("b", t.b)):
        async with sessions.session(actor.context) as s:
            note = Note(tenant_id=actor.context.tenant_id, body=f"{label}-secret")
            s.add(note)
            await s.flush()
            ids[label] = str(note.id)

    scope_a = TenantScope.of(t.a.context)
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(env.client, task_queue="test", workflows=[ReadNote], activities=[read_note]),
    ):
        own = await env.client.execute_workflow(
            ReadNote.run,
            args=[scope_a, ids["a"]],
            id=workflow_id(scope_a, "read-note", "own"),
            task_queue="test",
        )
        other = await env.client.execute_workflow(
            ReadNote.run,
            args=[scope_a, ids["b"]],
            id=workflow_id(scope_a, "read-note", "other"),
            task_queue="test",
        )
    assert own == "a-secret"
    assert other is None  # tenant B's row is invisible to a workflow scoped to tenant A


def test_scope_and_ids_are_validated() -> None:
    with pytest.raises(BadRequest):
        TenantScope("not-a-uuid", "x").context()
    scope = TenantScope(str(uuid.uuid4()), "u")
    assert workflow_id(scope, "export", "2026-11").startswith(scope.tenant_id)
    with pytest.raises(BadRequest):
        workflow_id(scope, "export", "../../other")
