"""Confidential results of zero-argument tools must expire too."""

from datetime import UTC, datetime, timedelta

from nexiqon_core.lifecycle import RetentionPolicy
from nexiqon_tool_gateway.lifecycle import ToolLifecycle
from nexiqon_tool_gateway.models import ToolCall
from sqlalchemy import update

pytest_plugins = ["services.tool-gateway.tests.conftest"]


def test_retention_erases_result_when_tool_arguments_are_empty(stack):
    from uuid import UUID

    call = stack.invoke("account-lookup")
    assert call["ok"]

    async def check():
        db = stack.client.app.state.db
        tenant = stack.tenants.a.context.tenant_id
        async with db.scoped({"tenant_id": str(tenant)}) as session:
            await session.execute(
                update(ToolCall)
                .where(ToolCall.id == UUID(call["call_id"]))
                .values(created_at=datetime.now(UTC) - timedelta(days=90))
            )
        lifecycle = ToolLifecycle("tool-gateway", db, stack.secrets)
        purged = await lifecycle.purge_expired(
            tenant, RetentionPolicy(tool_results_days=1)
        )
        async with db.scoped({"tenant_id": str(tenant)}) as session:
            row = await session.get(ToolCall, UUID(call["call_id"]))
            print(
                "Purged:",
                purged,
                "empty arguments:",
                row.arguments == {},
                "result still present:",
                row.result is not None,
            )
            assert row.result is None

    stack.client.portal.call(check)
